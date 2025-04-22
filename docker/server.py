import os
from flask import Flask, jsonify, request
import re
import brotli
import requests
from bs4 import BeautifulSoup
from llama_cpp import Llama
import threading

# --- CONFIG from ENV ---
API_KEY = os.environ.get("API_KEY")
BASE_URL = os.environ.get("BASE_URL")
DATASTORE_PATH = os.environ.get("DATASTORE_PATH", "/datastore")
LLM_MODEL_PATH = os.environ.get("LLM_MODEL_PATH")

HEADERS = {"x-api-key": API_KEY}

KEYWORDS = [
    "in stock", "out of stock", "unavailable", "sold out",
    "pick up", "add to cart", "check stores", "not available"
]

llm = Llama(model_path=LLM_MODEL_PATH, n_ctx=2048, n_threads=6)

app = Flask(__name__)



@app.route('/repair', methods=['POST'])
def repair_watch_from_url():
    try:
        # Accept from args, form, or JSON
        data = request.get_json(silent=True) or {}
        watch_url = (
            request.args.get("watch_url") or
            request.form.get("watch_url") or
            data.get("watch_url", "")
        )

        if not watch_url:
            return jsonify({"status": "error", "message": "Missing watch_url"}), 400

        match = re.search(r'/edit/([a-f0-9-]+)', watch_url)
        if not match:
            return jsonify({"status": "error", "message": "Invalid watch_url format"}), 400

        watch_uuid = match.group(1)
        print(f"🔔 Received watch notification: {watch_uuid}")

        # Respond immediately
        def background_repair():
            try:
                watch = get_watch_detail(watch_uuid)
                last_error = watch.get("last_error", "")
                status = watch.get("status", "").lower()

                if not last_error and "error" not in status:
                    print(f"✅ Watch {watch_uuid} is healthy. Skipping repair.")
                    return

                html, _ = read_latest_html_br(watch_uuid)
                if not html:
                    print(f"⚠️ No snapshot found for {watch_uuid}")
                    return

                candidate_selectors = simplify_html_for_llm_css(html)
                selector = find_valid_selector_with_retries(candidate_selectors, html)

                if selector:
                    updated = update_watch_css(watch_uuid, selector)
                    if updated:
                        print(f"🛠️ Repaired {watch_uuid} with selector: {selector}")
                        recheck_watch(watch_uuid)
                    else:
                        print(f"❌ Failed to update watch {watch_uuid}")
                else:
                    print(f"❌ No valid selector found for {watch_uuid}")
            except Exception as e:
                print(f"❌ Background repair failed: {e}")

        threading.Thread(target=background_repair).start()
        return jsonify({"status": "accepted", "message": "Repair scheduled"}), 200

    except Exception as e:
        print(f"❌ Exception in /repair: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


HEADERS = {"x-api-key": API_KEY}

KEYWORDS = [
    "in stock", "out of stock", "unavailable", "sold out",
    "pick up", "add to cart", "check stores", "not available"
]

# --- INIT LLaMA ---
llm = Llama(model_path=LLM_MODEL_PATH, n_ctx=2048, n_threads=6)

# --- WATCH HELPERS ---
def get_watch_ids():
    response = requests.get(f"{BASE_URL}/watch", headers=HEADERS)
    response.raise_for_status()
    return list(response.json().keys())

def get_watch_detail(watch_id):
    print(f"📡 Fetching watch detail for {watch_id}")
    response = requests.get(f"{BASE_URL}/watch/{watch_id}", headers=HEADERS)
    response.raise_for_status()
    return response.json()

def recheck_watch(watch_id):
    print(f"Rechecking {watch_id}")
    response = requests.get(f"{BASE_URL}/watch/{watch_id}?recheck=1", headers=HEADERS)
    response.raise_for_status()
    return response.json()

def read_latest_html_br(watch_uuid):
    watch_dir = os.path.join(DATASTORE_PATH, watch_uuid)
    if not os.path.exists(watch_dir):
        return None, None

    snapshot_files = [
        f for f in os.listdir(watch_dir)
        if f.endswith(".html.br") and f.split(".")[0].isdigit()
    ]
    if not snapshot_files:
        return None, None

    snapshot_files.sort(key=lambda x: int(x.split(".")[0]), reverse=True)
    latest_file = snapshot_files[0]
    full_path = os.path.join(watch_dir, latest_file)

    try:
        with open(full_path, "rb") as f:
            html = brotli.decompress(f.read()).decode("utf-8")
            return html, latest_file
    except Exception as e:
        print(f"⚠️ Failed to decompress {latest_file} for {watch_uuid}: {e}")
        return None, latest_file

def simplify_html_for_llm_css(html):
    from bs4 import BeautifulSoup
    import re


    def get_css_selector(element):
        path = []
        while element and element.name and element.name != '[document]':
            tag = element.name
            if element.get('id'):
                # Escape invalid characters for ID selectors
                safe_id = re.sub(r'[^a-zA-Z0-9_-]', lambda m: '\\' + m.group(), element['id'])
                tag += f"#{safe_id}"
            elif element.get('class'):
                # Only use the first class and escape it
                first_class = element['class'][0]
                safe_class = re.sub(r'[^a-zA-Z0-9_-]', lambda m: '\\' + m.group(), first_class)
                tag += f".{safe_class}"
            path.insert(0, tag)
            element = element.parent
        return ' > '.join(path)

    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()

    pattern = re.compile('|'.join(re.escape(k) for k in KEYWORDS), re.IGNORECASE)
    matches = soup.find_all(string=pattern)

    seen = set()
    results = []
    for i, match in enumerate(matches):
        parent = match.parent
        if not parent:
            continue
        css_path = get_css_selector(parent)
        key = (css_path, match.strip())
        if key not in seen:
            seen.add(key)
            results.append(f"Option {len(seen)}: EOS{css_path}BOS [text: \"{match.strip()}\"]")

    return ''.join(results)

def ask_llama_for_main_item_selector(simplified_html):
    examples = """
Example 1:
Option 1: EOShtml > body > div.container > div.product-main > div > button.buyBOS [text: "Add to Cart"]
Option 2: EOShtml > body > div.sidebar > div.carousel > div > buttonBOS [text: "Add to Cart"]
CSS Selector:
BOShtml > body > div.container > div.product-main > div > button.buyEOS

Example 2:
Option 1: EOSbody > main > section.product-detail > div.buy-button > buttonBOS [text: "Out of Stock"]
Option 2: EOSbody > footer > div.newsletter > button.subscribeBOS [text: "Subscribe"]
CSS Selector:
BOSbody > main > section.product-detail > div.buy-button > buttonEOS

Example 3:
Option 1: EOSbody > div.modal > div > button.closeBOS [text: "Close"]
Option 2: EOSbody > div.main-content > div.product > div.cta > button.add-to-cartBOS [text: "Add to Cart"]
CSS Selector:
BOSbody > div.main-content > div.product > div.cta > button.add-to-cartEOS

Example 4:
Option 1: EOShtml > body > header > nav > ul > li.cartBOS [text: "Cart"]
Option 2: EOShtml > body > div.page > section.main-product > div.stock-status > spanBOS [text: "Sold Out"]
CSS Selector:
BOShtml > body > div.page > section.main-product > div.stock-status > spanEOS

Example 5:
Option 1: EOShtml > body > div#sponsored > div.carousel > buttonBOS [text: "Buy Now"]
Option 2: EOShtml > body > div#main > div.product-box > div.info > button.purchaseBOS [text: "Buy Now"]
CSS Selector:
BOShtml > body > div#main > div.product-box > div.info > button.purchaseEOS

Example 6:
Option 1: EOShtml > body > div.main > section.featured-products > div > button.buyBOS [text: "Add to Cart"]
Option 2: EOShtml > body > div.main > section.product-overview > div > button.buyBOS [text: "Add to Cart"]
CSS Selector:
BOShtml > body > div.main > section.product-overview > div > button.buyEOS

Example 7:
Option 1: EOShtml > body > div.container > aside.sidebar > div.ad-block > buttonBOS [text: "Buy"]
Option 2: EOShtml > body > div.container > main.product-page > div.actions > button.ctaBOS [text: "Buy"]
CSS Selector:
BOShtml > body > div.container > main.product-page > div.actions > button.ctaEOS

Example 8:
Option 1: EOShtml > body > div.wrapper > div.related-products > button.addBOS [text: "Add to Cart"]
Option 2: EOShtml > body > div.wrapper > div.main-product > div > button.addBOS [text: "Add to Cart"]
CSS Selector:
BOShtml > body > div.wrapper > div.main-product > div > button.addEOS

Example 9:
Option 1: EOShtml > body > main#content > div#product-container > div.stock > span.statusBOS [text: "Out of Stock"]
Option 2: EOShtml > body > footer > div.info > spanBOS [text: "Company Info"]
CSS Selector:
BOShtml > body > main#content > div#product-container > div.stock > span.statusEOS

Example 10:
Option 1: EOShtml > body > div.main > div.product-display > div.status > labelBOS [text: "In Stock"]
Option 2: EOShtml > body > div.sidebar > div > labelBOS [text: "In Stock"]
CSS Selector:
BOShtml > body > div.main > div.product-display > div.status > labelEOS
"""
    
    prompt = (
        f"{examples}\n\n"
        "You are given a list of CSS selectors for elements that refer to stock information on a product page.\n"
        "Only ONE of them refers to the MAIN product. The rest may refer to related items, bundles, or ads.\n\n"
        "Your job is to identify the selector that most likely targets the MAIN product.\n"
        "- Return ONLY the CSS selector of the main product, on a single line.\n"
        "- Surround your answer with BOS and EOS. Example: BOS .main-container > button.buy EOS\n"
        "- Ignore any '[text: ...]' annotations — they are only context.\n"
        "- DO NOT include classes or IDs that look like random hashes or auto-generated strings (e.g. '.x8h3f94')\n"
        "- Prefer more general selectors (e.g. use a parent or skip overly specific levels if needed).\n"
        "- Do not include any explanation, text, or formatting. Only the selector line with BOS and EOS.\n\n"
        f"{simplified_html}\n"
        "CSS Selector:"
    )

    result = llm(prompt, max_tokens=200)
    # result = llm(prompt, max_tokens=200)
    print(f"result : {result}")

    text = result["choices"][0]["text"]
    text = re.sub(r'\[text:.*?\]', '', text)
    text = re.sub(r'BOS.*BOS', 'BOS', text)
    match = re.search(r'BOS(.*?)EOS', text, re.DOTALL)
    return match.group(1).strip() if match else ""

def test_selector_on_snapshot(html, selector):
    soup = BeautifulSoup(html, "html.parser")
    try:
        match = soup.select_one(selector)
        if not match:
            return False
        text = match.get_text(strip=True).lower()
        return any(word in text for word in KEYWORDS)
    except Exception as e:
        print(f"⚠️ Selector error: {e}")
        return False

def find_valid_selector_with_retries(candidate_selectors, html, max_attempts=3):
    print("🧪 Simplified HTML preview:")
    print(candidate_selectors)
    for attempt in range(max_attempts):
        selector = ask_llama_for_main_item_selector(candidate_selectors)
        print(f"🤖 LLaMA Suggestion (attempt {attempt + 1}): {selector}")
        if selector and test_selector_on_snapshot(html, selector):
            return selector
    return None

def update_watch_css(watch_id, selector):
    payload = {
        "include_filters": [f"{selector.strip()}"]
    }
    try:
        response = requests.put(
            f"{BASE_URL}/watch/{watch_id}",
            headers={**HEADERS, "Content-Type": "application/json"},
            json=payload
        )
        response.raise_for_status()
        print(f"✅ Watch updated with CSS selector: {selector}")
        return True
    except Exception as e:
        print(f"❌ Failed to update watch {watch_id}: {e}")
        return False

# --- MAIN LOGIC ---
def auto_repair_failed_watches():
    failed = []
    for watch_id in get_watch_ids():
        watch = get_watch_detail(watch_id)
        last_error = watch.get("last_error", "")
        status = watch.get("status", "").lower()

        if last_error or "error" in status:
            html, _ = read_latest_html_br(watch_id)
            if not html:
                continue

            candidate_selectors = simplify_html_for_llm_css(html)
            selector = find_valid_selector_with_retries(candidate_selectors, html)

            if selector:
                updated = update_watch_css(watch_id, selector)
                if updated:
                    failed.append((watch_id, selector))
            else:
                print(f"❌ LLaMA failed to identify a valid selector for {watch_id}")

    return failed


if __name__ == '__main__':
    print(f"Listening on {os.environ.get('PORT', 5000)}")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
