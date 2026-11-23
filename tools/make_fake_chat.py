#!/usr/bin/env python
"""
Generate deterministic fake WhatsApp chat files for demo mode.
Creates:
  data/raw_chats/demo__fake_android.txt
  data/raw_chats/demo__fake_iphone.txt
Each file contains about 400 lines of fabricated messages including:
  - Fake sender names (Dealer 01, Dealer 02, ...)
  - Fake phone numbers (0300-0000001, etc.)
  - Listings in English, Roman Urdu, and Urdu script
  - Sizes: 5 marla, 10 marla, 1 kanal
  - Blocks: DEMO_BLOCK_A, DEMO_BLOCK_B, DEMO_EXEC (from market/blocks_demo.json)
  - Features: corner/middle, facing, NDC open/closed, possession, developed
  - Fake price levels with some outliers
  - Noise: greetings, system lines, <Media omitted>, multi-line messages
  - Duplicate posts (same plot in both files)
  - Phone numbers that require scrubbing
"""
import os
import random
from datetime import datetime, timedelta

# Fixed seed for determinism
SEED = 42
random.seed(SEED)

# Output directory
RAW_CHATS_DIR = "data/raw_chats"
os.makedirs(RAW_CHATS_DIR, exist_ok=True)

# File paths
ANDROID_FILE = os.path.join(RAW_CHATS_DIR, "demo__fake_android.txt")
IPHONE_FILE = os.path.join(RAW_CHATS_DIR, "demo__fake_iphone.txt")

# Demo blocks (should match market/blocks_demo.json)
DEMO_BLOCKS = ["DEMO_BLOCK_A", "DEMO_BLOCK_B", "DEMO_EXEC"]

# Fake data
SELLERS = [f"Dealer {i:02d}" for i in range(1, 11)]
PHONE_NUMBERS = [f"0300-000000{i}" for i in range(1, 11)]
URBAN_AREAS = ["Faisal Hills", "Bahria Town", "DHA", "Gulberg"]
FACTORS = ["corner", "middle"]
FACINGS = ["North", "South", "East", "West", "North-East", "North-West"]
NDC_STATUSES = ["open", "not open"]
POSSESSION_STATUSES = [True, False]
DEVELOPED_STATUSES = [True, False]
FEATURES_LIST = ["gas", "electricity", "water", "boundary wall", "plantation"]

# Price ranges (in PKR) for different sizes
SIZE_PRICE_RANGES = {
    5: (1_000_000, 2_000_000),
    10: (2_000_000, 4_000_000),
    12: (2_400_000, 4_800_000),  # 1 kanal = 20 marla, but we use 12 for demo? Actually 1 kanal = 20 marla. Let's use 20.
    20: (4_000_000, 8_000_000),
}
# We'll use 5, 10, 20 marla for 5, 10, 1 kanal
SIZES = [5, 10, 20]

# Urdu numerals for Roman Urdu substitution
URDU_DIGITS = {
    '0': '۰',
    '1': '۱',
    '2': '۲',
    '3': '۳',
    '4': '۴',
    '5': '۵',
    '6': '۶',
    '7': '۷',
    '8': '۸',
    '9': '۹',
}

def to_urdu_digits(num_str):
    """Convert ASCII digits to Urdu digits."""
    return ''.join(URDU_DIGITS.get(ch, ch) for ch in num_str)

def to_roman_urdu(text):
    """Convert Urdu script text to Roman Urdu (approximate)."""
    # This is a very rough approximation for demo purposes
    urdu_to_roman = {
        'آ': 'aa', 'ا': 'a', 'ب': 'b', 'پ': 'p', 'ت': 't', 'ٹ': 'th',
        'ج': 'j', 'چ': 'ch', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ڈ': 'dh',
        'ر': 'r', 'ڑ': 'rh', 'ز': 'z', 'ژ': 'zh', 'س': 's', 'ش': 'sh',
        'ص': 's', 'ض': 'z', 'ط': 't', 'ظ': 'z', 'ع': 'aa', 'غ': 'gh',
        'ف': 'f', 'ق': 'q', 'ک': 'k', 'گ': 'g', 'ل': 'l', 'م': 'm',
        'ن': 'n', 'و': 'o', 'ہ': 'h', 'ء': '', 'ی': 'i', 'ے': 'e',
    }
    # We'll do a simple replacement for demo; not accurate but sufficient
    roman = []
    for ch in text:
        roman.append(urdu_to_roman.get(ch, ch))
    return ''.join(roman)

def generate_listing_variants(base_text):
    """Generate English, Roman Urdu, and Urdu script variants of a listing."""
    # We'll create three variants: English, Roman Urdu, and Urdu script
    # For simplicity, we'll use the same base text and apply transformations
    english = base_text
    # Roman Urdu: replace some words with Urdu-like transliteration (very rough)
    roman_urdu = base_text.replace("Faisal Hills", "فيصل ہلس")
    roman_urdu = roman_urdu.replace("Dealer", "ڈیلر")
    # Urdu script: we'll use a few Urdu words for demo
    urdu_script = base_text.replace("Faisal Hills", "فیصل ہلس")
    urdu_script = urdu_script.replace("Dealer", "ڈیلر")
    urdu_script = urdu_script.replace("for sale", "بیچنے کے لیے")
    return [english, roman_urdu, urdu_script]

def generate_message(sender, phone, text, timestamp):
    """Generate a message in Android or iPhone format."""
    # We'll generate both formats; the caller will choose
    date_str = timestamp.strftime("%m/%d/%y")
    time_str = timestamp.strftime("%I:%M %p")
    # Android format: [DD/MM/YY, HH:MM:SS AM/PM] Sender: Message
    android = f"[{date_str}, {time_str}] {sender}: {text}"
    # iPhone format: [DD/MM/YY, HH:MM:SS AM/PM] Sender: Message
    # Actually, iPhone format is similar but uses 24-hour time? We'll use same for simplicity.
    # In reality, iPhone uses: [DD/MM/YY, HH:MM:SS] Sender: Message
    # We'll make them slightly different by using 24-hour for iPhone
    time_str_iphone = timestamp.strftime("%H:%M")
    iphone = f"[{date_str}, {time_str_iphone}] {sender}: {text}"
    return android, iphone

def main():
    # Generate a base timestamp and increment for each message
    base_time = datetime(2026, 10, 1, 9, 0, 0)
    time_increment = timedelta(minutes=5)

    android_lines = []
    iphone_lines = []

    # We'll generate 200 messages per file (so about 400 lines with multi-line etc.)
    num_messages = 200

    # Keep track of which plots we've used to create duplicates
    used_plots = set()

    for i in range(num_messages):
        # Pick random data
        seller = random.choice(SELLERS)
        phone = random.choice(PHONE_NUMBERS)
        size = random.choice(SIZES)
        block = random.choice(DEMO_BLOCKS)
        factor = random.choice(FACTORS)
        facing = random.choice(FACINGS)
        ndc = random.choice(NDC_STATUSES)
        possession = random.choice(POSSESSION_STATUSES)
        developed = random.choice(DEVELOPED_STATUSES)
        features = random.sample(FEATURES_LIST, k=random.randint(0, 3))

        # Generate price with some outliers
        low, high = SIZE_PRICE_RANGES[size]
        price = random.randint(low, high)
        # 5% chance of outlier (too low or too high)
        if random.random() < 0.05:
            if random.random() < 0.5:
                price = random.randint(100_000, low // 2)  # too low
            else:
                price = random.randint(high * 2, high * 5)  # too high

        # Generate a fake plot number
        plot_no = f"Plot-{random.randint(1, 100)}"
        # To create duplicates, sometimes we reuse a plot
        if random.random() < 0.1 and used_plots:
            plot_no = random.choice(list(used_plots))
        else:
            used_plots.add(plot_no)

        # Base listing text in English
        base_text = (
            f"{size} marla plot in {block}, {factor}, facing {facing}, "
            f"NDC {ndc}, {'possession' if possession else 'no possession'}, "
            f"{'developed' if developed else 'undeveloped'}, "
            f"features: {', '.join(features) if features else 'none'}, "
            f"price: {price:,} PKR, contact: {phone}"
        )

        # Generate language variants
        variants = generate_listing_variants(base_text)
        # Pick one variant at random
        text = random.choice(variants)

        # Sometimes add noise: greetings, system lines, etc.
        if random.random() < 0.1:
            # Greeting
            text = random.choice(["Assalam o Alaikum!", "Hello!", "Hi there!"]) + " " + text
        if random.random() < 0.05:
            # System line
            text = text + "\n<Media omitted>"
        if random.random() < 0.05:
            # Multi-line message
            text = text + "\nSecond line of the same message."

        # Generate timestamp
        timestamp = base_time + (i * time_increment)

        # Create Android and iPhone message formats
        android_msg, iphone_msg = generate_message(seller, phone, text, timestamp)

        android_lines.append(android_msg)
        iphone_lines.append(iphone_msg)

    # Write files
    with open(ANDROID_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(android_lines))
    with open(IPHONE_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(iphone_lines))

    print(f"Generated {ANDROID_FILE} and {IPHONE_FILE}")

if __name__ == "__main__":
    main()
