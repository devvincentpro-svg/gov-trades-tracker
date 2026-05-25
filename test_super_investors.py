import requests, xml.etree.ElementTree as ET

SEC_HEADERS = {"User-Agent": "GovTradesTracker admin@example.com"}

acc = "000119312526226661"
xml_url = f"https://www.sec.gov/Archives/edgar/data/1067983/{acc}/53405.xml"
r = requests.get(xml_url, headers=SEC_HEADERS, timeout=15)

# Print raw snippet to see structure
print(r.text[:2000])
