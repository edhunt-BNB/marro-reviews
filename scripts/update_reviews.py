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
OUTPUT_HTML = "index.html"

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
    """Categorize 5-star review into specific categories"""
    if not review_text or len(review_text) < 10:
        return [], ""
    
    prompt = f"""Analyze this 5-star Trustpilot review for Marro (a cat food company) and categorize it.

CATEGORIES (select 1-2 that best fit):
1. "High Quality Ingredients/Product" - mentions quality, ingredients, freshness, real meat, etc.
2. "Customer Service" - mentions helpful staff, support, communication, responsiveness
3. "Fussy Cats" - mentions picky/fussy cat that loves the food
4. "Took a While But Now Love It" - cat was hesitant at first but eventually loved it
5. "Subscription Benefits" - mentions convenience, delivery, subscription flexibility, easy to manage
6. "Changed My Cat's Life / Health Benefits" - mentions health improvements, coat, energy, digestion, weight

REVIEW:
"{review_text}"

Respond in JSON:
{{"categories": ["Category 1"], "summary": "One sentence summary focusing on why they gave 5 stars"}}
"""
    
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a review analyzer. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=200
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
        return data.get("categories", []), data.get("summary", "")
    
    except Exception as e:
        print(f"    AI error: {e}")
        return [], ""


def load_existing_reviews():
    """Load existing reviews from JSON file"""
    if os.path.exists(REVIEWS_JSON):
        with open(REVIEWS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("reviews", []), data.get("last_timestamp", "0")
    return [], "0"


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
        
        .summary-badge {
            background: var(--marro-pink);
            color: var(--marro-dark-maroon);
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 13px;
            margin-bottom: 12px;
            font-style: italic;
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
                    {f'<div class="summary-badge">💡 {summary}</div>' if summary else ''}
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


def main():
    print("=" * 60)
    print("MARRO 5-STAR REVIEW UPDATER")
    print(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    if not SLACK_BOT_TOKEN or not GROQ_API_KEY:
        print("ERROR: Missing environment variables (SLACK_BOT_TOKEN or GROQ_API_KEY)")
        return
    
    # Load existing reviews
    existing_reviews, last_timestamp = load_existing_reviews()
    print(f"\nExisting reviews: {len(existing_reviews)}")
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
            new_reviews = []
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
            
            # Categorize new 5-star reviews
            for i, review in enumerate(new_5star):
                print(f"  [{i+1}/{len(new_5star)}] Categorizing: {review['date']}...")
                categories, summary = categorize_5star_review(review["review_text"], groq_client)
                review["categories"] = categories
                review["summary"] = summary
            
            # Merge with existing
            existing_timestamps = {r["timestamp"] for r in existing_reviews}
            for review in new_5star:
                if review["timestamp"] not in existing_timestamps:
                    existing_reviews.append(review)
            
            # Sort by date (newest first)
            existing_reviews.sort(key=lambda x: x.get("timestamp", "0"), reverse=True)
            
            # Save updated reviews
            save_reviews(existing_reviews, latest_ts)
            print(f"\nTotal reviews now: {len(existing_reviews)}")
        else:
            print("No new messages found.")
    
    # Group by category
    reviews_by_category = {cat: [] for cat in CATEGORIES_5STAR}
    for review in existing_reviews:
        for cat in review.get("categories", []):
            if cat in reviews_by_category:
                reviews_by_category[cat].append(review)
    
    # Generate HTML
    print("\nGenerating HTML...")
    html = generate_html(reviews_by_category)
    
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"Saved: {OUTPUT_HTML}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("CATEGORY BREAKDOWN")
    print("=" * 60)
    for cat, reviews in reviews_by_category.items():
        print(f"  {cat}: {len(reviews)} reviews")
    
    print("\n✅ UPDATE COMPLETE!")


if __name__ == "__main__":
    main()
