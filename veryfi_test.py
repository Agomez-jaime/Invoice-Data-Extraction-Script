from veryfi import Client
import os
import re
import json
from pprint import pprint

def split_records(data, start_keywords):
    records = []
    current = ""

    for line in data:
        line = line.strip()
        if any(line.startswith(k) for k in start_keywords):
            if current:
                records.append(current.strip())
            current = line
        else:
            current += " " + line
    if current:
        records.append(current.strip())
    return records

def parse_record(record):
    # Match trailing numbers (with commas and decimals), possibly with one trailing non-number field
    numbers = re.findall(r'[-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?', record)
    parts = re.split(r'[-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?', record)

    # Rebuild the title (everything before the first number)
    title = parts[0].strip()

    # Handle case where second part has text; join it with the first part
    if len(parts) > 1 and any(c.isalpha() for c in parts[1]):
        title += " " + parts[1].strip()
        # Keep only the numeric part for the second item
        numbers = [num for num in numbers if re.match(r'\d', num)]

    # Ensure the second item only has a number, or leave empty if invalid
    second_item = numbers[0] if numbers else ""

    # Edge case: trailing part is not numeric (like "to xyz"), extract and keep it in title
    trailing = record[record.rfind(numbers[-1]) + len(numbers[-1]):].strip()
    if trailing:
        title += " " + trailing

    # Ensure there are enough numbers in the list
    while len(numbers) < 3:
        numbers.append("")

    return [title] + numbers[:3]


def rearrange_list2(data):
    new_data = []
    moved_number = None

    for i, item in enumerate(data):
        item = item.strip()

        # Functionality 1: Starts with number and then text
        if i > 0:
            match_start = re.match(r'^(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(.*)', item)
            if match_start:
                number = match_start.group(1)
                text = match_start.group(2)
                data[0] += " " + text.strip()
                moved_number = number
                continue

        # Functionality 2: Ends with number
        match_end = re.match(r'^(.*?)(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)$', item)
        if match_end:
            text = match_end.group(1).strip()
            number = match_end.group(2)
            if text:
                new_data.append(text)
            new_data.append(number)
        else:
            new_data.append(item)

    if moved_number:
        new_data.append(moved_number)

    return new_data

def clean_lines(data, start_keywords):
    while any(not any(line.strip().startswith(k) for k in start_keywords) for line in data):
        cleaned = []
        skip_next = False
        for i, line in enumerate(data):
            if skip_next:
                skip_next = False
                continue
            line = line.rstrip("\n")
            if any(line.startswith(k) for k in start_keywords):
                cleaned.append(line)
            else:
                if cleaned:
                    cleaned[-1] += " " + line
                else:
                    cleaned.append(line)
        data = cleaned
    return data

def parse_table_lines(text):
    lines = text.splitlines()
    table_lines = []
    header_pattern = re.compile(r'Description\s+Quantity\s+Rate\s+Amount', re.IGNORECASE)
    footer_pattern = re.compile(r'(?i)(invoice\s+no|total\s+usd|remit|balance|questions|make\s+payments|page\s+\d+\s+of\s+\d+)', re.IGNORECASE)

    capturing = False

    for line in lines:
        clean_line = line.strip()

        # Detect the start of a new table header (even if it's on a second page)
        if header_pattern.search(clean_line):
            capturing = True
            continue  # Skip header line

        if capturing:
            # If it looks like a footer or unrelated metadata, stop capturing temporarily
            if not clean_line or footer_pattern.search(clean_line):
                capturing = False
                continue

            # Otherwise, keep adding table lines
            table_lines.append(clean_line)

    return table_lines

def get_company_name_after_invoice_block(ocr_text):
    lines = ocr_text.splitlines()
    for i, line in enumerate(lines):
        if "Invoice No." in line:
            # Move to the line after the dates
            for j in range(i + 2, len(lines)):  # +2 skips the line with the date values
                candidate = lines[j].strip()
                if candidate:  # Non-empty line
                    return candidate
    return None
def extract_invoice_data(ocr_text):
    # Format exclusion logic: check keywords unique to target format
    if "switch" not in ocr_text or "Invoice" not in ocr_text or "Description" not in ocr_text:
        return None  # Reject unmatched formats

    result = {}
    #Headers
    # Regex to match "Switch, Ltd."
    match = re.search(r"Please make payments to:\s*([A-Za-z\s,]+Ltd\.)", ocr_text)
    result["vendor name"] = match.group(1)

    #regex to capture address
    match = re.search(r"([A-Za-z\s,]+TX\s+\d{5}-\d{4})\s+PO\s+Box\s+\d+", ocr_text)

    if match:
        # Capture the address and clean the result
        address = match.group(0).replace('Invoice', '')
        address = address.replace('switch', '').strip()
        result["vendor address"] = address

    #Now for bill to name
    result["bill to name"] = get_company_name_after_invoice_block(ocr_text)
    # Regex to capture invoice number just after "Invoice No."
    match = re.search(r"Invoice No\.\s*(?:\d{2}/\d{2}/\d{2}\s+){2}(\d+)", ocr_text)
    result["invoice number"] = match.group(1) if match else None
    #Now invoice date
    # Use a regex to find the date in MM/DD/YY format
    match = re.search(r"\b(\d{2}/\d{2}/\d{2})\b", ocr_text)
    if match:
        invoice_date = match.group(1)
        result["date"] = invoice_date

    # Regex to find the total USD amount
    match = re.search(r"Total USD\s*\$([\d,]+\.\d{2})", ocr_text)
    total_usd = float(match.group(1).replace(",", ""))

    #Get table data
    table_data = parse_table_lines(ocr_text)
    # Keywords to start a new entry - filter previous data
    start_keywords = ("Installation", "Carrier", "Transport", "Special", "Item")

    cleaned = clean_lines(table_data, start_keywords)
    # Replace multiple tabs with a single tab in each entry
    cleaned = [re.sub(r'\t+', '&&&', entry) for entry in cleaned]
    clean_clean = []
    # Separate in description, quantity, rate and amount
    for entry in cleaned:
        e = entry.split("&&&")
        arranged = rearrange_list2(e)
        clean_clean.append(arranged)
    result['line item'] = []

    for i in range(len(clean_clean)):
        line = {}
        line['sku'] = i+1
        line['description'] = clean_clean[i][0]
        line['quantity'] = clean_clean[i][1]
        line['tax_rate'] = clean_clean[i][2]
        line['price'] = clean_clean[i][3]
        line['total'] = total_usd
        result['line item'].append(line)
    return result


# For a quick test. Encode for actual script
client_id = "vrfMWi9uZibhO4RDCa5AwzgSYAmZy5hYsw5vWXe"
client_secret = "0yvcJLIzh1FgT2sCkkOr4vuU5lA06TZNktTbtHXUHXRleSCmYf9mmZHvxgePaLp3ZPwAxuJVAxa4kYhNB7GVsUwP3Fhc60ouBRVP3Jo7ct32j1rPsb6pPW8ZB6FK8EMY"
username = "a.gomezj"
api_key = "f1a676a515710cf88988e332dbc2f8ee"

# Initialize the Veryfi Client
veryfi_client = Client(client_id, client_secret, username, api_key)

#Get the document, process, and extract the OCR text

folder_path = "./Documents-20250415T142828Z-001/Documents/"
for filename in os.listdir(folder_path):
    if filename.lower().endswith((".jpg", ".jpeg", ".png", ".pdf")):
        file_path = os.path.join(folder_path, filename)
        response = veryfi_client.process_document(file_path)
        ocr_text = response.get("ocr_text", "")
        result= extract_invoice_data(ocr_text)
        # Dump it into a JSON file
        f_name = filename[:-4] + '.json'
        with open(f_name, 'w') as f:
            json.dump(result, f, indent=4)
