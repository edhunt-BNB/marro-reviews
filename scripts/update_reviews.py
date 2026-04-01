"""
Marro 5-Star Review Updater for GitHub Actions
===============================================
Fetches new 5-star reviews from Slack, categorizes with AI, and updates the HTML.
"""

import os
import json
import requests
from datetime import datetime
from groq import Groq

# Configuration from environment variables
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SLACK_CHANNEL_NAME = "marro-trustpilot"

# Files
REVIEWS_JSON = "reviews_data.json"
NEEDS_REVIEW_JSON = "needs_review.json"
OUTPUT_HTML = "index.html"
NEEDS_REVIEW_HTML = "Ed_to_check_reviews.html"

# 5-Star Review Categories
CATEGORIES_5STAR = [
    "High Quality Ingredients/Product",
    "Customer Service",
    "Fussy Cats",
    "Took a While But Now Love It",
    "Subscription Benefits",
    "Changed My Cat's Life / Health Benefits"
]


def get_channel_id(token, channel_name):
    """Find channel ID using bot's conversations"""
    print(f"Looking for channel: #{channel_name}")
    
    response = requests.get(
        "https://slack.com/api/users.conversations",
        headers={"Authorization": f"Bearer {token}"},
        params={"types": "public_channel,private_channel", "limit": 200}
    )
    
    data = response.json()
    if not data.get("ok"):
        print(f"Error: {data.get('error')}")
        return None
    
    for channel in data.get("channels", []):
        if channel["name"] == channel_name:
            print(f"Found channel: {channel['name']} (ID: {channel['id']})")
            return channel["id"]
    
    print(f"Channel #{channel_name} not found.")
    return None


def fetch_messages_since(token, channel_id, oldest_ts=None):
    """Fetch messages from channel since a timestamp"""
    print(f"Fetching messages since {oldest_ts or 'beginning'}...")
    
    all_messages = []
    cursor = None
    
    while True:
        params = {"channel": channel_id, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        if oldest_ts:
            params["oldest"] = oldest_ts
        
        response = requests.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {token}"},
            params=params
        )
        
        data = response.json()
        if not data.get("ok"):
            print(f"Error: {data.get('error')}")
            break
        
        messages = data.get("messages", [])
        all_messages.extend(messages)
        print(f"  Fetched {len(messages)} messages (total: {len(all_messages)})")
        
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    
    return all_messages


def parse_review_from_message(message):
    """Extract review data from a Slack message"""
    text = message.get("text", "")
    ts = message.get("ts", "")
    
    try:
        date = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except:
        date = "Unknown"
    
    attachments = message.get("attachments", [])
    
    review_text = text
    reviewer_name = ""
    star_rating = 0
    title = ""
    
    for attachment in attachments:
        if attachment.get("text"):
            review_text = attachment.get("text", text)
        if attachment.get("author_name"):
            reviewer_name = attachment.get("author_name", "")
        if attachment.get("title"):
            title = attachment.get("title", "")
        
        footer = attachment.get("footer", "")
        star_count = footer.count("★") + footer.count("⭐")
        if star_count > 0:
            star_rating = min(star_count, 5)
    
    return {
        "date": date,
        "timestamp": ts,
        "reviewer_name": reviewer_name,
        "star_rating": star_rating,
        "title": title,
        "review_text": review_text
    }


def categorize_5star_review(review_text, groq_client):
    """Categorize 5-star review into ONE specific category with confidence check"""
    if not review_text or len(review_text) < 10:
        return None, False  # category, is_confident
    
    prompt = f"""You are categorizing 5-star Trustpilot reviews for Marro (a cat food company).

STRICT RULES:
- Select ONLY ONE category that BEST fits the review
- Only select a category if you are HIGHLY CONFIDENT (90%+ sure)
- If the review could fit multiple categories equally, or doesn't clearly fit any, set confidence to "low"

CATEGORIES (pick exactly ONE):

1. "High Quality Ingredients/Product" 
   - Review MUST explicitly mention: quality, ingredients, freshness, real meat, natural, healthy food
   - NOT just "my cat loves it" - needs specific quality mentions

2. "Customer Service" 
   - Review MUST mention: staff, support team, advisor, communication, help received, response
   - The PRIMARY focus of the review is about service received

3. "Fussy Cats" 
   - Review MUST explicitly say the cat is: picky, fussy, difficult eater, won't eat other food, refuses food
   - The cat's pickiness must be the MAIN POINT of the review

4. "Took a While But Now Love It" 
   - Review MUST mention: took time, hesitant at first, didn't like it initially, gradual transition, eventually loved it
   - There must be a BEFORE (didn't like) and AFTER (now loves) story

5. "Subscription Benefits" 
   - Review MUST mention: delivery, subscription, convenience, easy to order, flexible, doorstep
   - The PRIMARY focus is about the subscription/delivery service

6. "Changed My Cat's Life / Health Benefits" 
   - Review MUST mention: health improvement, better coat, more energy, digestion, weight loss/gain, vet, medical
   - There must be a SPECIFIC health benefit mentioned

REVIEW:
"{review_text}"

Respond in JSON ONLY:
{{"category": "Category Name or null", "confidence": "high" or "low", "reason": "brief reason for choice"}}
"""
    
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a strict review categorizer. Only categorize if highly confident. Respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,  # Lower temperature for more consistent results
            max_tokens=150
        )
        
        result = response.choices[0].message.content
        
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            result = result.split("```")[1].split("```")[0]
        
        start = result.find("{")
        end = result.rfind("}") + 1
        if start != -1 and end > start:
            result = result[start:end]
        
        data = json.loads(result)
        category = data.get("category")
        confidence = data.get("confidence", "low")
        reason = data.get("reason", "")
        
        # Only return category if confidence is high and category is valid
        if category and confidence == "high" and category in CATEGORIES_5STAR:
            return category, True
        else:
            print(f"    Low confidence or invalid: {category} ({confidence}) - {reason}")
            return category, False
    
    except Exception as e:
        print(f"    AI error: {e}")
        return None, False


def load_existing_reviews():
    """Load existing reviews from JSON file"""
    if os.path.exists(REVIEWS_JSON):
        with open(REVIEWS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("reviews", []), data.get("last_timestamp", "0")
    return [], "0"


def load_needs_review():
    """Load reviews that need manual categorization"""
    if os.path.exists(NEEDS_REVIEW_JSON):
        with open(NEEDS_REVIEW_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("reviews", [])
    return []


def save_reviews(reviews, last_timestamp):
    """Save reviews to JSON file"""
    data = {
        "last_updated": datetime.now().isoformat(),
        "last_timestamp": last_timestamp,
        "total_reviews": len(reviews),
        "reviews": reviews
    }
    with open(REVIEWS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_needs_review(reviews):
    """Save reviews that need manual categorization"""
    data = {
        "last_updated": datetime.now().isoformat(),
        "total_reviews": len(reviews),
        "reviews": reviews
    }
    with open(NEEDS_REVIEW_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def send_slack_notification(num_reviews):
    """Send Slack DM to Ed when there are reviews to check"""
    if num_reviews == 0:
        return
    
    # Ed's Slack user ID (we'll need to look this up or use email)
    # For now, we'll post to a channel or use webhook
    
    message = {
        "text": f"📋 *Marro Review Alert*\n\n{num_reviews} new review(s) need manual categorization.\n\n👉 <https://edhunt-bnb.github.io/marro-reviews/Ed_to_check_reviews.html|Click here to review>"
    }
    
    try:
        # Try to send DM to Ed using his email
        # First, look up user by email
        response = requests.get(
            "https://slack.com/api/users.lookupByEmail",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            params={"email": "edwardhunt@butternutbox.com"}
        )
        
        data = response.json()
        if data.get("ok"):
            user_id = data["user"]["id"]
            
            # Open a DM channel
            dm_response = requests.post(
                "https://slack.com/api/conversations.open",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                json={"users": user_id}
            )
            
            dm_data = dm_response.json()
            if dm_data.get("ok"):
                channel_id = dm_data["channel"]["id"]
                
                # Send the message
                msg_response = requests.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                    json={
                        "channel": channel_id,
                        "text": message["text"],
                        "unfurl_links": False
                    }
                )
                
                if msg_response.json().get("ok"):
                    print(f"  📨 Slack notification sent to Ed")
                else:
                    print(f"  ⚠️ Failed to send Slack message: {msg_response.json().get('error')}")
            else:
                print(f"  ⚠️ Failed to open DM: {dm_data.get('error')}")
        else:
            print(f"  ⚠️ Could not find Slack user: {data.get('error')}")
    
    except Exception as e:
        print(f"  ⚠️ Slack notification error: {e}")


def generate_html(reviews_by_category):
    """Generate the HTML landing page with tabs"""
    
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>5 Star Marro Reviews</title>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --marro-maroon: #80020F;
            --marro-dark-maroon: #3A070d;
            --marro-pink: #E2C5C5;
            --marro-mustard: #C88131;
            --marro-cream: #FDF8F3;
            --marro-white: #FFFFFF;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'IBM Plex Sans', sans-serif;
            background: var(--marro-cream);
            color: var(--marro-dark-maroon);
            min-height: 100vh;
        }
        
        .header {
            background: linear-gradient(135deg, var(--marro-maroon), var(--marro-dark-maroon));
            color: white;
            padding: 40px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 36px;
            font-weight: 700;
            margin-bottom: 8px;
        }
        
        .header .stars {
            font-size: 28px;
            color: var(--marro-mustard);
            margin-bottom: 12px;
        }
        
        .header .subtitle {
            font-size: 18px;
            opacity: 0.9;
        }
        
        .header .last-updated {
            font-size: 12px;
            opacity: 0.7;
            margin-top: 10px;
        }
        
        .tabs {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            background: white;
            padding: 16px 20px;
            gap: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .tab {
            padding: 12px 20px;
            border: 2px solid var(--marro-maroon);
            background: white;
            border-radius: 25px;
            cursor: pointer;
            font-weight: 500;
            font-size: 14px;
            transition: all 0.2s;
            white-space: nowrap;
            color: var(--marro-dark-maroon);
        }
        
        .tab:hover {
            background: var(--marro-pink);
        }
        
        .tab.active {
            background: var(--marro-maroon);
            color: white;
        }
        
        .tab .count {
            background: var(--marro-mustard);
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            margin-left: 6px;
        }
        
        .tab.active .count {
            background: white;
            color: var(--marro-maroon);
        }
        
        .content {
            max-width: 1200px;
            margin: 0 auto;
            padding: 30px 20px;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
        
        .category-header {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .category-header h2 {
            font-size: 28px;
            color: var(--marro-maroon);
            margin-bottom: 8px;
        }
        
        .category-header p {
            color: #666;
            font-size: 16px;
        }
        
        .reviews-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 24px;
        }
        
        .review-card {
            background: white;
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.08);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .review-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.12);
        }
        
        .review-stars {
            color: var(--marro-mustard);
            font-size: 20px;
            margin-bottom: 12px;
        }
        
        .review-title {
            font-weight: 600;
            font-size: 18px;
            margin-bottom: 12px;
            color: var(--marro-dark-maroon);
        }
        
        .review-text {
            color: #555;
            line-height: 1.6;
            margin-bottom: 16px;
            font-size: 15px;
        }
        
        .review-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-top: 12px;
            border-top: 1px solid #eee;
            font-size: 13px;
            color: #888;
        }
        
        .review-author {
            font-weight: 500;
        }
        
        
        @media (max-width: 768px) {
            .header { padding: 30px 20px; }
            .header h1 { font-size: 28px; }
            .tabs { padding: 12px; gap: 8px; }
            .tab { padding: 10px 14px; font-size: 13px; }
            .reviews-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="stars">★★★★★</div>
        <h1>What Our Happy Cat Parents Say</h1>
        <div class="subtitle">Real 5-star reviews from the Marro community</div>
        <div class="last-updated">Last updated: ''' + datetime.now().strftime("%d %B %Y at %H:%M") + '''</div>
    </div>
    
    <div class="tabs" id="tabs">
'''
    
    for i, (category, reviews) in enumerate(reviews_by_category.items()):
        active = "active" if i == 0 else ""
        tab_id = category.replace(" ", "_").replace("/", "_").replace("'", "")
        html += f'''        <div class="tab {active}" data-tab="{tab_id}">{category}<span class="count">{len(reviews)}</span></div>\n'''
    
    html += '''    </div>
    
    <div class="content">
'''
    
    descriptions = {
        "High Quality Ingredients/Product": "Cat parents who love our fresh, real ingredients",
        "Customer Service": "Praise for our amazing support team",
        "Fussy Cats": "Even the pickiest cats can't resist",
        "Took a While But Now Love It": "Patience pays off - these cats are now obsessed",
        "Subscription Benefits": "The convenience that keeps them coming back",
        "Changed My Cat's Life / Health Benefits": "Real health transformations"
    }
    
    for i, (category, reviews) in enumerate(reviews_by_category.items()):
        active = "active" if i == 0 else ""
        tab_id = category.replace(" ", "_").replace("/", "_").replace("'", "")
        
        html += f'''        <div id="{tab_id}" class="tab-content {active}">
            <div class="category-header">
                <h2>{category}</h2>
                <p>{descriptions.get(category, "")}</p>
            </div>
            <div class="reviews-grid">
'''
        
        for review in reviews[:50]:
            title = review.get("title", "").replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
            text = review.get("review_text", "").replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
            summary = review.get("summary", "").replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
            reviewer = review.get("reviewer_name", "Happy Customer").replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
            date = review.get("date", "")
            
            if len(text) > 300:
                text = text[:300] + "..."
            
            html += f'''                <div class="review-card">
                    <div class="review-stars">★★★★★</div>
                    {f'<div class="review-title">{title}</div>' if title else ''}
                    <div class="review-text">{text}</div>
                    <div class="review-meta">
                        <span class="review-author">{reviewer if reviewer else "Verified Buyer"}</span>
                        <span>{date}</span>
                    </div>
                </div>
'''
        
        html += '''            </div>
        </div>
'''
    
    html += '''    </div>
    
    <script>
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(tab.dataset.tab).classList.add('active');
            });
        });
    </script>
</body>
</html>
'''
    
    return html


def generate_needs_review_html(reviews):
    """Generate the HTML page for manual review categorization"""
    
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ed to Check - Marro Reviews</title>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --marro-maroon: #80020F;
            --marro-dark-maroon: #3A070d;
            --marro-pink: #E2C5C5;
            --marro-mustard: #C88131;
            --marro-cream: #FDF8F3;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'IBM Plex Sans', sans-serif;
            background: var(--marro-cream);
            color: var(--marro-dark-maroon);
            min-height: 100vh;
            padding: 20px;
        }
        
        .header {
            background: linear-gradient(135deg, var(--marro-mustard), #a66a28);
            color: white;
            padding: 30px;
            text-align: center;
            border-radius: 16px;
            margin-bottom: 30px;
        }
        
        .header h1 { font-size: 28px; margin-bottom: 8px; }
        .header p { opacity: 0.9; }
        
        .review-count {
            background: white;
            padding: 15px 25px;
            border-radius: 25px;
            display: inline-block;
            margin-top: 15px;
            font-weight: 600;
            color: var(--marro-dark-maroon);
        }
        
        .reviews-container {
            max-width: 900px;
            margin: 0 auto;
        }
        
        .review-card {
            background: white;
            border-radius: 16px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }
        
        .review-card.categorized {
            opacity: 0.5;
            border: 3px solid #4CAF50;
        }
        
        .review-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }
        
        .review-stars { color: var(--marro-mustard); font-size: 20px; }
        .review-date { color: #888; font-size: 13px; }
        .review-title { font-weight: 600; font-size: 18px; margin-bottom: 10px; }
        .review-text { color: #555; line-height: 1.6; margin-bottom: 15px; }
        .review-author { color: #888; font-size: 13px; font-style: italic; }
        
        .category-buttons {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 20px;
            padding-top: 15px;
            border-top: 2px dashed #ddd;
        }
        
        .category-btn {
            padding: 10px 16px;
            border: 2px solid var(--marro-maroon);
            background: white;
            color: var(--marro-dark-maroon);
            border-radius: 20px;
            cursor: pointer;
            font-family: inherit;
            font-size: 13px;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .category-btn:hover {
            background: var(--marro-maroon);
            color: white;
        }
        
        .category-btn.selected {
            background: #4CAF50;
            border-color: #4CAF50;
            color: white;
        }
        
        .success-msg {
            background: #4CAF50;
            color: white;
            padding: 10px 15px;
            border-radius: 8px;
            margin-top: 10px;
            display: none;
        }
        
        .no-reviews {
            text-align: center;
            padding: 60px;
            color: #888;
        }
        
        .no-reviews h2 { color: #4CAF50; margin-bottom: 10px; }
        
        .instructions {
            background: var(--marro-pink);
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 30px;
            text-align: center;
        }
        
        .instructions p { margin-bottom: 10px; }
        .instructions strong { color: var(--marro-maroon); }
    </style>
</head>
<body>
    <div class="header">
        <h1>📋 Ed to Check - Review Queue</h1>
        <p>Reviews that need manual categorization</p>
        <div class="review-count">''' + str(len(reviews)) + ''' reviews to check</div>
    </div>
    
    <div class="reviews-container">
'''
    
    if not reviews:
        html += '''        <div class="no-reviews">
            <h2>✅ All caught up!</h2>
            <p>No reviews need manual categorization.</p>
        </div>
'''
    else:
        html += '''        <div class="instructions">
            <p><strong>Instructions:</strong> Click a category button to assign the review.</p>
            <p>The review will be moved to the main page automatically.</p>
        </div>
'''
        for review in reviews:
            title = review.get("title", "").replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
            text = review.get("review_text", "").replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
            reviewer = review.get("reviewer_name", "").replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
            date = review.get("date", "")
            timestamp = review.get("timestamp", "")
            ai_suggestion = review.get("ai_suggestion", "")
            
            html += f'''        <div class="review-card" id="review-{timestamp}">
            <div class="review-header">
                <div class="review-stars">★★★★★</div>
                <div class="review-date">{date}</div>
            </div>
            {f'<div class="review-title">{title}</div>' if title else ''}
            <div class="review-text">{text}</div>
            <div class="review-author">— {reviewer if reviewer else "Anonymous"}</div>
            {f'<div style="margin-top:10px;padding:8px 12px;background:#fff3cd;border-radius:8px;font-size:12px;">🤖 AI suggested: <strong>{ai_suggestion}</strong> (low confidence)</div>' if ai_suggestion else ''}
            <div class="category-buttons">
'''
            for cat in CATEGORIES_5STAR:
                cat_id = cat.replace(" ", "_").replace("/", "_").replace("'", "")
                html += f'''                <button class="category-btn" onclick="assignCategory('{timestamp}', '{cat}')">{cat}</button>
'''
            
            html += f'''            </div>
            <div class="success-msg" id="success-{timestamp}">✅ Assigned! Refresh to see updated list.</div>
        </div>
'''
    
    html += '''    </div>
    
    <script>
        function assignCategory(timestamp, category) {
            // Store in localStorage for now (manual process)
            const assignments = JSON.parse(localStorage.getItem('marro_assignments') || '{}');
            assignments[timestamp] = category;
            localStorage.setItem('marro_assignments', JSON.stringify(assignments));
            
            // Visual feedback
            const card = document.getElementById('review-' + timestamp);
            card.classList.add('categorized');
            document.getElementById('success-' + timestamp).style.display = 'block';
            
            // Update all buttons in this card
            card.querySelectorAll('.category-btn').forEach(btn => {
                if (btn.textContent === category) {
                    btn.classList.add('selected');
                }
            });
            
            console.log('Assigned:', timestamp, '->', category);
            console.log('All assignments:', assignments);
            
            // Show instructions for manual sync
            alert('Category assigned: ' + category + '\\n\\nTo sync to the main page, run the update script or trigger the GitHub Action.');
        }
        
        // On page load, check for any stored assignments and mark them
        document.addEventListener('DOMContentLoaded', () => {
            const assignments = JSON.parse(localStorage.getItem('marro_assignments') || '{}');
            Object.keys(assignments).forEach(timestamp => {
                const card = document.getElementById('review-' + timestamp);
                if (card) {
                    card.classList.add('categorized');
                    document.getElementById('success-' + timestamp).style.display = 'block';
                }
            });
        });
    </script>
</body>
</html>
'''
    
    return html


def main():
    print("=" * 60)
    print("MARRO 5-STAR REVIEW UPDATER")
    print(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    if not SLACK_BOT_TOKEN or not GROQ_API_KEY:
        print("ERROR: Missing environment variables (SLACK_BOT_TOKEN or GROQ_API_KEY)")
        return
    
    # Load existing data
    existing_reviews, last_timestamp = load_existing_reviews()
    needs_review = load_needs_review()
    
    print(f"\nExisting categorized reviews: {len(existing_reviews)}")
    print(f"Reviews needing manual check: {len(needs_review)}")
    print(f"Last timestamp: {last_timestamp}")
    
    # Get channel ID
    channel_id = get_channel_id(SLACK_BOT_TOKEN, SLACK_CHANNEL_NAME)
    if not channel_id:
        print("Failed to find channel. Using existing data only.")
        if not existing_reviews:
            return
    else:
        # Fetch new messages
        new_messages = fetch_messages_since(SLACK_BOT_TOKEN, channel_id, last_timestamp)
        
        if new_messages:
            print(f"\nProcessing {len(new_messages)} new messages...")
            
            groq_client = Groq(api_key=GROQ_API_KEY)
            new_5star = []
            latest_ts = last_timestamp
            
            for msg in new_messages:
                if msg.get("subtype") == "channel_join":
                    continue
                
                ts = msg.get("ts", "0")
                if float(ts) > float(latest_ts):
                    latest_ts = ts
                
                review = parse_review_from_message(msg)
                if review["review_text"] and len(review["review_text"]) > 20:
                    if review["star_rating"] == 5:
                        new_5star.append(review)
            
            print(f"Found {len(new_5star)} new 5-star reviews")
            
            # Categorize new 5-star reviews with confidence check
            confident_reviews = []
            uncertain_reviews = []
            
            existing_timestamps = {r["timestamp"] for r in existing_reviews}
            needs_review_timestamps = {r["timestamp"] for r in needs_review}
            
            for i, review in enumerate(new_5star):
                # Skip if already processed
                if review["timestamp"] in existing_timestamps or review["timestamp"] in needs_review_timestamps:
                    continue
                
                print(f"  [{i+1}/{len(new_5star)}] Categorizing: {review['date']} - {review.get('title', '')[:30]}...")
                category, is_confident = categorize_5star_review(review["review_text"], groq_client)
                
                if is_confident and category:
                    # High confidence - add to main list with single category
                    review["category"] = category
                    review["categories"] = [category]  # Keep for backward compatibility
                    confident_reviews.append(review)
                    print(f"    ✅ Confident: {category}")
                else:
                    # Low confidence - add to manual review queue
                    review["ai_suggestion"] = category  # Store AI's guess for reference
                    review["categories"] = []
                    uncertain_reviews.append(review)
                    print(f"    ⚠️ Needs manual review")
            
            # Add confident reviews to main list
            for review in confident_reviews:
                existing_reviews.append(review)
            
            # Add uncertain reviews to needs_review list
            for review in uncertain_reviews:
                needs_review.append(review)
            
            # Sort by date (newest first)
            existing_reviews.sort(key=lambda x: x.get("timestamp", "0"), reverse=True)
            needs_review.sort(key=lambda x: x.get("timestamp", "0"), reverse=True)
            
            # Save updated data
            save_reviews(existing_reviews, latest_ts)
            save_needs_review(needs_review)
            
            print(f"\n✅ Added {len(confident_reviews)} confident reviews to main list")
            print(f"⚠️ Added {len(uncertain_reviews)} reviews to manual queue")
            print(f"Total categorized: {len(existing_reviews)}")
            print(f"Total needing review: {len(needs_review)}")
            
            # Send Slack notification if there are new reviews to check
            if len(uncertain_reviews) > 0:
                send_slack_notification(len(uncertain_reviews))
        else:
            print("No new messages found.")
    
    # Group by category (single category per review now)
    reviews_by_category = {cat: [] for cat in CATEGORIES_5STAR}
    for review in existing_reviews:
        cat = review.get("category") or (review.get("categories", [None])[0] if review.get("categories") else None)
        if cat and cat in reviews_by_category:
            reviews_by_category[cat].append(review)
    
    # Generate main HTML
    print("\nGenerating HTML files...")
    html = generate_html(reviews_by_category)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved: {OUTPUT_HTML}")
    
    # Generate needs-review HTML
    needs_review_html = generate_needs_review_html(needs_review)
    with open(NEEDS_REVIEW_HTML, "w", encoding="utf-8") as f:
        f.write(needs_review_html)
    print(f"  Saved: {NEEDS_REVIEW_HTML}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("CATEGORY BREAKDOWN (Confident Reviews)")
    print("=" * 60)
    for cat, reviews in reviews_by_category.items():
        print(f"  {cat}: {len(reviews)} reviews")
    print(f"\n  ⚠️ Needs Manual Review: {len(needs_review)} reviews")
    
    print("\n✅ UPDATE COMPLETE!")


if __name__ == "__main__":
    main()
