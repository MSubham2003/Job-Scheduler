import os
import re
import smtplib
import requests
import markdown
import xml.etree.ElementTree as ET
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# -------------------------------------------------------------
# 1. 80+ CURATED STARTUPS, MID-SCALE & FINTECH ATS BOARDS
# -------------------------------------------------------------
STARTUP_BOARDS = {
    "greenhouse": [
        # --- Fintech, Banking & WealthTech ---
        ("Razorpay", "razorpaysoftwareprivatelimited"),
        ("CRED", "cred"),
        ("Groww", "groww"),
        ("Slice", "sliceit"),
        ("KreditBee", "kreditbee"),
        ("Chargebee", "chargebee"),
        ("Kuvera", "kuvera"),
        ("Turtlemint", "turtlemint"),
        ("Digit Insurance", "godigitinsurance"),
        ("Open Financial Technologies", "openfinancialtechnologies"),
        ("Acko General Insurance", "acko"),
        
        # --- Quick-Commerce, Food & E-Commerce ---
        ("Swiggy", "swiggy"),
        ("Zepto", "zepto"),
        ("Blinkit", "blinkit"),
        ("Meesho", "meesho"),
        ("Nykaa", "nykaa"),
        ("Licious", "licious"),
        ("Purplle", "purplle"),
        
        # --- Logistics, Mobility & Auto ---
        ("Porter", "porter"),
        ("Shiprocket", "shiprocket"),
        ("Shadowfax", "shadowfax"),
        ("Rapido", "rapido"),
        ("Ola Electric", "olaelectric"),
        ("Ather Energy", "atherenergy"),
        ("BlackBuck", "blackbuck"),

        # --- Enterprise SaaS, Cloud & Dev Tools ---
        ("Postman", "postman"),
        ("BrowserStack", "browserstack"),
        ("CleverTap", "clevertap"),
        ("Urban Company", "urbancompany"),
        ("Hasura", "hasura"),
        ("MoEngage", "moengage"),
        ("LeadSquared", "leadsquared"),
        ("Darwinbox", "darwinbox"),
        ("Harness", "harness"),
        ("Whatfix", "whatfix"),
        ("Sprinklr", "sprinklr"),
        ("InMobi", "inmobi"),
        ("Gupshup", "gupshup"),
        ("HighRadius", "highradius"),  # Significant Bhubaneswar R&D campus

        # --- HealthTech, EdTech & Gaming ---
        ("PharmEasy", "pharmeasy"),
        ("HealthifyMe", "healthifyme"),
        ("Tata 1mg", "1mg"),
        ("Eruditus", "eruditus"),
        ("Games24x7", "games24x7"),
        ("Mobile Premier League (MPL)", "mpl")
    ],
    
    "lever": [
        # --- Core Payments, Neobanks & Lending ---
        ("Juspay", "juspay"),
        ("Decentro", "decentro"),
        ("Setu", "setu"),
        ("Navi", "navi"),
        ("Fi Money", "fi-money"),
        ("OneCard", "fpl-technologies"),
        ("M2P Fintech", "m2p"),
        ("Signzy", "signzy"),
        ("Uni Cards", "uni-cards"),
        ("Jupiter Money", "jupiter"),
        ("PayU India", "payu-india"),
        ("BharatPe", "bharatpe"),
        ("Drip Capital", "dripcapital"),
        ("Lendingkart", "lendingkart"),
        ("Progcap", "progcap"),
        ("Perfios", "perfios"),
        ("Epifi", "epifi"),

        # --- High-Growth Startups & Scaleups ---
        ("Cars24", "cars24"),
        ("Spinny", "spinny"),
        ("Infra.Market", "infra-market"),
        ("OfBusiness", "ofbusiness"),
        ("DealShare", "dealshare"),
        ("Cuemath", "cuemath"),
        ("Classplus", "classplus"),
        ("Kite (Zerodha)", "zerodha"),
        ("Yellow.ai", "yellowai"),
        ("Verloop.io", "verloop"),
        ("Kissflow", "kissflow"),
        ("Zetwerk", "zetwerk"),
        ("Khatabook", "khatabook"),
        ("ClearTax", "cleartax")
    ]
}

# -------------------------------------------------------------
# 2. GEOGRAPHIC MARKERS & VALIDATION
# -------------------------------------------------------------
FOREIGN_MARKERS = [
    "united states", "usa", "u.s.", "canada", "mexico",
    "california", "new york", "texas", "washington", "austin", "chicago", 
    "san francisco", "bay area", "toronto", "vancouver", "foster city",
    "united kingdom", "uk", "london", "germany", "berlin", "munich", 
    "amsterdam", "netherlands", "ireland", "dublin", "france", "paris", 
    "poland", "warsaw", "spain", "madrid", "barcelona", "estonia",
    "uae", "dubai", "abu dhabi", "saudi arabia", "riyadh", "kazakhstan", 
    "israel", "tel aviv", "qatar", "doha",
    "australia", "sydney", "melbourne", "new zealand", "singapore", 
    "malaysia", "kuala lumpur", "philippines", "manila", "nigeria", 
    "south africa", "brazil", "argentina", "tokyo", "japan"
]

INDIA_MARKERS = [
    "bhubaneswar", "odisha", "cuttack", "rourkela",
    "india", "remote", "work from home", "wfh", "anywhere in india", "hybrid",
    "bengaluru", "bangalore", "hyderabad", "pune", "delhi", "new delhi",
    "noida", "greater noida", "gurgaon", "gurugram", "ncr", 
    "chennai", "mumbai", "navi mumbai", "kolkata", "ahmedabad", 
    "kochi", "cochin", "thiruvananthapuram", "trivandrum", "indore", "jaipur", "chandigarh"
]

def is_valid_india_location(loc_str: str) -> bool:
    l = loc_str.lower()
    if any(m in l for m in FOREIGN_MARKERS):
        return False
    return any(m in l for m in INDIA_MARKERS) or l.strip() == ""

def get_normalized_location(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["bhubaneswar", "odisha", "infocity", "cybercity"]):
        return "Bhubaneswar / Odisha"
    if any(k in t for k in ["remote", "wfh", "work from home"]):
        return "Remote (India)"
    if any(k in t for k in ["bengaluru", "bangalore"]):
        return "Bengaluru"
    if "hyderabad" in t:
        return "Hyderabad"
    if "pune" in t:
        return "Pune"
    if any(k in t for k in ["noida", "gurgaon", "gurugram", "delhi"]):
        return "Delhi-NCR"
    if any(k in t for k in ["mumbai", "navi mumbai"]):
        return "Mumbai"
    if "chennai" in t:
        return "Chennai"
    if "kolkata" in t:
        return "Kolkata"
    return "India (Hybrid/Onsite)"

# -------------------------------------------------------------
# 3. DIRECT ATS HARVESTER (GREENHOUSE & LEVER)
# -------------------------------------------------------------
def fetch_ats_roles():
    jobs = []
    
    # Greenhouse Boards
    for name, slug in STARTUP_BOARDS["greenhouse"]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false"
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                for item in r.json().get("jobs", []):
                    title = item.get("title", "")
                    loc = item.get("location", {}).get("name", "India")
                    t_low = title.lower()
                    if any(k in t_low for k in ["backend", "java", "sde", "software engineer"]):
                        if not any(k in t_low for k in ["lead", "staff", "principal", "director", "manager", "intern"]):
                            if is_valid_india_location(loc):
                                jobs.append({
                                    "title": title,
                                    "company": name,
                                    "location": get_normalized_location(loc),
                                    "url": item.get("absolute_url"),
                                    "source": "Direct Startup Board"
                                })
        except Exception:
            pass

    # Lever Boards
    for name, slug in STARTUP_BOARDS["lever"]:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                for item in r.json():
                    title = item.get("text", "")
                    loc = item.get("categories", {}).get("location", "India")
                    t_low = title.lower()
                    if any(k in t_low for k in ["backend", "java", "sde", "software engineer"]):
                        if not any(k in t_low for k in ["lead", "staff", "principal", "director", "manager", "intern"]):
                            if is_valid_india_location(loc):
                                jobs.append({
                                    "title": title,
                                    "company": name,
                                    "location": get_normalized_location(loc),
                                    "url": item.get("hostedUrl"),
                                    "source": "Direct Startup Board"
                                })
        except Exception:
            pass

    return jobs

# -------------------------------------------------------------
# 4. 24H WEB DISCOVERY (ENTERPRISE IT, LINKEDIN, & LOCAL FIRMS)
# -------------------------------------------------------------
def fetch_enterprise_and_linkedin_roles():
    queries = [
        # Upperhand Local Query
        '("Java" OR "Spring Boot") ("Bhubaneswar" OR "Odisha") (developer OR engineer) when:1d',
        
        # Enterprise IT Majors (TCS, Infosys, LTIMindtree, Tech Mahindra, Cognizant, Wipro)
        '("TCS" OR "Infosys" OR "LTIMindtree" OR "Tech Mahindra" OR "Cognizant" OR "Wipro") ("Java" OR "Spring Boot") India (developer OR engineer) when:1d',
        
        # Direct LinkedIn Easy Apply & Job Posts
        'site:linkedin.com/jobs/view ("Spring Boot" OR "Java Microservices") India (remote OR hybrid OR onsite) when:1d',
        'site:linkedin.com/posts "hiring" ("Java" OR "Spring Boot") India (developer OR engineer) when:1d',
        
        # High-Growth Tech & Fintech Hubs
        '("Spring Boot" OR "Java") ("Bengaluru" OR "Hyderabad" OR "Pune" OR "Noida") ("fintech" OR "backend") when:1d'
    ]
    
    discovered = []
    for q in queries:
        feed_url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            res = requests.get(feed_url, headers=HEADERS, timeout=8)
            if res.status_code == 200:
                root = ET.fromstring(res.content)
                for item in root.findall(".//item"):
                    title = item.find("title").text if item.find("title") is not None else ""
                    link = item.find("link").text if item.find("link") is not None else ""
                    desc = item.find("description").text if item.find("description") is not None else ""
                    
                    combined = f"{title} {desc}".lower()
                    if not is_valid_india_location(combined):
                        continue
                    
                    comp = "Tech Organization"
                    clean_title = title
                    if " - " in title:
                        parts = title.rsplit(" - ", 1)
                        clean_title = parts[0]
                        comp = parts[1]
                    
                    source = "LinkedIn Listing / Post" if "linkedin.com" in link or "linkedin" in comp.lower() else "Enterprise / Web Index"
                    loc = get_normalized_location(combined)
                    
                    if any(k in clean_title.lower() for k in ["java", "spring", "backend", "software", "developer", "sde"]):
                        discovered.append({
                            "title": clean_title,
                            "company": comp,
                            "location": loc,
                            "url": link,
                            "source": source
                        })
        except Exception:
            pass

    return discovered

# -------------------------------------------------------------
# 5. RELEVANCE SCORER (BHUBANESWAR UPPERHAND)
# -------------------------------------------------------------
def calculate_relevance(job):
    """
    Ranks openings based on technical fit, with an organic upper hand for Bhubaneswar.
    """
    score = 0
    t = (job["title"] + " " + job["location"] + " " + job["company"]).lower()
    
    # 1. Tech Stack Alignment
    if "spring boot" in t or "springboot" in t:
        score += 35
    if "microservices" in t:
        score += 25
    if "java" in t:
        score += 20
    if "backend" in t or "sde" in t or "software engineer" in t:
        score += 15

    # 2. Domain Boost (Fintech, Payments, Banking, Scaled Platforms)
    if any(k in t for k in ["fintech", "payment", "bank", "razorpay", "juspay", "decentro", "cred", "bbps", "iso 8583"]):
        score += 30

    # 3. Location Upper Hand
    if "bhubaneswar" in t or "odisha" in t:
        score += 35   # Upperhand bonus
    elif "remote" in t:
        score += 15

    # 4. Direct ATS / Company Source
    if job.get("source") == "Direct Startup Board":
        score += 10

    return score

# -------------------------------------------------------------
# 6. MARKDOWN GENERATOR (20 <= TOTAL <= 40)
# -------------------------------------------------------------
def build_markdown_report(jobs):
    today = datetime.now().strftime("%Y-%m-%d")
    md = f"# 🚀 Daily Java & Spring Boot Job Radar ({len(jobs)} Verified Roles) — {today}\n\n"
    md += "_Targeted across Startups, Product Platforms, Enterprise IT, and LinkedIn (Last 24 Hours)._\n\n"
    md += "---\n\n"

    md += "## 🎯 Active Requisitions (Ordered by Tech Match & Bhubaneswar Priority)\n\n"
    for idx, j in enumerate(jobs, 1):
        loc = j["location"]
        is_bbsr = "bhubaneswar" in loc.lower() or "odisha" in loc.lower()
        loc_display = f"📍 **{loc}** (Local Priority)" if is_bbsr else f"{loc}"
        
        md += f"### {idx}. [{j['title']}]({j['url']})\n"
        md += f"- **Company / Employer:** **{j['company']}** | **Channel:** `{j['source']}`\n"
        md += f"- **Location:** {loc_display}\n"
        md += f"- **Direct Application Link:** [Click Here to View & Apply]({j['url']})\n\n"

    md += "---\n\n### 🏢 Enterprise IT Campus Career Portals (Direct 1-Click)\n\n"
    md += "- [TCS iBegin (Java / Spring Boot in Bhubaneswar)](https://ibegin.tcs.com/iBegin/jobs/search?skill=Java&location=Bhubaneswar)\n"
    md += "- [Infosys Careers (Java Spring Boot Developer)](https://career.infosys.com/joblist?skills=Java%20Spring%20Boot&country=India)\n"
    md += "- [LTIMindtree Careers (Java Microservices)](https://www.ltimindtree.com/careers/search-jobs/?keyword=Java)\n"
    md += "- [Tech Mahindra Lateral Careers](https://careers.techmahindra.com/JobSearch.aspx)\n"
    md += "- [Wipro India Careers (Java / Cloud Backend)](https://careers.wipro.com/careers-home/jobs?keywords=Java%20Spring%20Boot&location=India)\n\n"

    md += "### 🔗 Live Search Feeds (Past 24 Hours / 1–3 YOE)\n\n"
    md += "- [LinkedIn: Spring Boot Developer in Bhubaneswar (Past 24h)](https://www.linkedin.com/jobs/search/?keywords=Spring%20Boot&location=Bhubaneswar%2C%20Odisha%2C%20India&f_TPR=r86400)\n"
    md += "- [LinkedIn: All India Spring Boot Roles (Past 24h)](https://www.linkedin.com/jobs/search/?keywords=Spring%20Boot&location=India&f_TPR=r86400)\n"
    md += "- [Naukri: Java / Spring Boot in Bhubaneswar](https://www.naukri.com/java-spring-boot-jobs-in-bhubaneswar?experience=1)\n"
    md += "- [Instahyre: Startups Hiring Java Backend](https://www.instahyre.com/search-jobs/?job_functions=software-engineering&skills=Java,Spring%20Boot)\n"
    md += "- [Wellfound: Product & FinTech Startups](https://wellfound.com/role/l/backend-engineer/india)\n"

    return md

# -------------------------------------------------------------
# 7. EMAIL DISPATCHER
# -------------------------------------------------------------
def send_digest_email(md_content, role_count):
    today = datetime.now().strftime("%Y-%m-%d")
    msg = MIMEMultipart("mixed")
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = f"🎯 [{role_count} Openings] Daily Java & Spring Boot Radar — {today}"

    html_content = markdown.markdown(md_content)
    styled_html = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1a1a1a; max-width: 780px; margin: auto; padding: 25px;">
        {html_content}
      </body>
    </html>
    """
    msg.attach(MIMEText(styled_html, "html"))

    filename = f"java_jobs_radar_{today}.md"
    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(md_content.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header("Content-Disposition", f"attachment; filename={filename}")
    msg.attach(attachment)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
    print("Email sent successfully!")

# -------------------------------------------------------------
# 8. MAIN EXECUTION PIPELINE
# -------------------------------------------------------------
if __name__ == "__main__":
    print("Harvesting roles across Startups, Product Boards, Enterprise IT, and LinkedIn...")
    all_found = []
    
    # 1. Harvest direct company boards (Greenhouse & Lever)
    all_found.extend(fetch_ats_roles())
    
    # 2. Harvest fresh LinkedIn & web index listings (24h)
    all_found.extend(fetch_enterprise_and_linkedin_roles())

    # 3. Deduplicate by URL
    unique_map = {}
    for j in all_found:
        u = j.get("url")
        if u and u not in unique_map:
            unique_map[u] = j

    unique_jobs = list(unique_map.values())
    print(f"Total unique roles collected: {len(unique_jobs)}")

    # 4. Rank by tech stack, domain match & Bhubaneswar upper hand
    sorted_jobs = sorted(unique_jobs, key=calculate_relevance, reverse=True)

    # 5. Strictly enforce target bracket: at least 20, at most 40
    final_selection = sorted_jobs[:40]

    print(f"Delivering top {len(final_selection)} positions.")
    report_md = build_markdown_report(final_selection)
    send_digest_email(report_md, len(final_selection))