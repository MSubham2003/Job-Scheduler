import os
import re
import json
import smtplib
import requests
import markdown
import xml.etree.ElementTree as ET
import google.generativeai as genai
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Non-Indian markers to drop immediately
FOREIGN_KEYWORDS = [
    "united states", "usa", "uk", "united kingdom", "london", "canada", 
    "toronto", "germany", "berlin", "australia", "sydney", "kazakhstan", 
    "dubai", "uae", "singapore", "nigeria", "mexico", "brazil", "foster city", "california"
]

INDIA_LOCATIONS = [
    "bhubaneswar", "odisha", "india", "bengaluru", "bangalore", 
    "hyderabad", "pune", "delhi", "noida", "gurgaon", "gurugram", 
    "chennai", "mumbai", "kolkata", "remote"
]

def is_valid_india_location(text: str) -> bool:
    t = text.lower()
    if any(foreign in t for foreign in FOREIGN_KEYWORDS):
        return False
    return any(loc in t for loc in INDIA_LOCATIONS)

def fetch_india_tech_feed():
    """Fetches real-time feeds filtered strictly for APAC / Anywhere remote."""
    jobs = []
    # Query Jobicy specifically for APAC / Worldwide Remote
    for geo in ["apac", "anywhere"]:
        url = f"https://jobicy.com/api/v2/remote-jobs?count=30&tag=java&geo={geo}"
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if res.status_code == 200:
                for item in res.json().get("jobs", []):
                    title = item.get("jobTitle", "")
                    desc = item.get("jobDescription", "")
                    geo_loc = item.get("jobGeo", "")
                    
                    if is_valid_india_location(geo_loc) or is_valid_india_location(desc):
                        jobs.append({
                            "title": title,
                            "company": item.get("companyName", "Tech Org"),
                            "url": item.get("url"),
                            "location": geo_loc if geo_loc else "Remote (India Eligible)",
                            "content": re.sub(r'<[^>]+>', ' ', desc)[:1500]
                        })
        except Exception as e:
            print(f"Jobicy feed error for {geo}: {e}")
    return jobs

def fetch_india_curated_rss():
    """Fetches from India-specific job search feeds."""
    queries = [
        '("Java" OR "Spring Boot") ("Bhubaneswar" OR "Odisha") (developer OR engineer) when:1d',
        '("Spring Boot" OR "Java microservices") ("Bengaluru" OR "Bangalore" OR "Hyderabad" OR "Pune") when:1d',
        '("Spring Boot") ("Fintech" OR "Payments" OR "Banking") India (developer OR engineer) when:1d',
        '("Java" AND "Spring Boot") ("Remote India" OR "Work from Home") developer when:1d'
    ]
    
    jobs = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for q in queries:
        feed_url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            res = requests.get(feed_url, headers=headers, timeout=12)
            if res.status_code == 200:
                root = ET.fromstring(res.content)
                for item in root.findall(".//item"):
                    title = item.find("title").text if item.find("title") is not None else ""
                    link = item.find("link").text if item.find("link") is not None else ""
                    desc = item.find("description").text if item.find("description") is not None else ""
                    clean_desc = re.sub(r'<[^>]+>', ' ', desc)

                    # Split Title - Company
                    comp = "Tech Company"
                    clean_title = title
                    if " - " in title:
                        parts = title.rsplit(" - ", 1)
                        clean_title = parts[0]
                        comp = parts[1]

                    # Strict India location verification
                    combined_text = f"{clean_title} {clean_desc}".lower()
                    if not is_valid_india_location(combined_text):
                        continue

                    loc = "Bhubaneswar / Odisha" if any(b in combined_text for b in ["bhubaneswar", "odisha"]) else "India (Hybrid/Remote)"

                    jobs.append({
                        "title": clean_title,
                        "company": comp,
                        "url": link,
                        "location": loc,
                        "content": clean_desc[:1500]
                    })
        except Exception as e:
            print(f"Error fetching RSS query: {e}")

    return jobs

def score_and_enrich_job(job):
    """Scores candidate alignment strictly for India/Bhubaneswar 1-3 YOE."""
    if not GEMINI_API_KEY:
        return None

    title_lower = job['title'].lower()
    disqualifiers = ["frontend", "react", "angular", "intern", "staff", "principal", "qa", "devops", "ios", "android", "vice president", "manager"]
    if any(k in title_lower for k in disqualifiers):
        return None

    response_schema = {
        "type": "object",
        "properties": {
            "fit": {"type": "boolean"},
            "match_score": {"type": "integer"},
            "experience": {"type": "string"},
            "detected_city": {"type": "string"},
            "is_bhubaneswar": {"type": "boolean"},
            "tech_stack": {
                "type": "array",
                "items": {"type": "string"}
            },
            "reason": {"type": "string"}
        },
        "required": ["fit", "match_score", "experience", "detected_city", "is_bhubaneswar", "tech_stack", "reason"]
    }

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": response_schema,
            "temperature": 0.1
        }
    )

    prompt = f"""
Candidate: Java Backend Engineer (1-3 YOE)[cite: 1].
Core Strengths: Java, Spring Boot, Microservices, PostgreSQL, Redis, GCP Pub/Sub, BBPS, ISO 8583, Payment APIs, Distributed Systems[cite: 1].
Target Location: India ONLY (Preference: Bhubaneswar, Remote-in-India, Bengaluru, Pune, Hyderabad).

STRICT DISQUALIFICATION RULES:
1. If the job is located OUTSIDE India, set "fit": false, "match_score": 0.
2. If the job strictly requires >4 years of experience, set "fit": false, "match_score": 0.
3. If the role does NOT involve Java/JVM backend, set "fit": false, "match_score": 0.

SCORING:
- 90-100: Located in Bhubaneswar OR Payment/Fintech Java roles in India[cite: 1].
- 75-89: Spring Boot / Java Microservices in India (Remote, Bengaluru, Pune, etc.)[cite: 1].
- <65: Weak match.

Job to Evaluate:
Title: {job['title']}
Company: {job['company']}
Location Field: {job['location']}
Description: {job['content']}
"""

    try:
        response = model.generate_content(prompt)
        data = json.loads(response.text)
        if data.get("fit") and data.get("match_score", 0) >= 65:
            return {**job, **data}
    except Exception as e:
        print(f"Scoring error for {job['title']}: {e}")

    return None

def build_markdown_report(matched_jobs):
    today = datetime.now().strftime("%Y-%m-%d")
    md = f"# 🚀 Fresh Java & Spring Boot Openings (Past 24 Hours) — {today}\n\n"
    md += f"_Strictly filtered for India | Priority: Bhubaneswar, Remote, and Fintech/Spring Boot._\n\n"
    md += "---\n\n"

    if matched_jobs:
        sorted_jobs = sorted(
            matched_jobs, 
            key=lambda x: (x.get("is_bhubaneswar", False), x.get("match_score", 0)), 
            reverse=True
        )

        bhubaneswar_jobs = [j for j in sorted_jobs if j.get("is_bhubaneswar")]
        other_india_jobs = [j for j in sorted_jobs if not j.get("is_bhubaneswar")]

        if bhubaneswar_jobs:
            md += "## 📍 Bhubaneswar & Odisha Local Openings\n\n"
            for idx, job in enumerate(bhubaneswar_jobs, 1):
                skills = ", ".join(job.get("tech_stack", [])[:4])
                md += f"### {idx}. [{job['title']}]({job['url']})\n"
                md += f"- **Company:** {job['company']} | **Match Score:** `{job.get('match_score')}/100`\n"
                md += f"- **Location:** 📍 **{job.get('detected_city', 'Bhubaneswar')}** | **Exp:** {job.get('experience')}\n"
                md += f"- **Tech:** {skills}\n"
                md += f"- **Why:** _{job.get('reason')}_\n\n"

        if other_india_jobs:
            md += "## 🌐 All-India & Remote / Tech Hubs (Ranked by Fit)\n\n"
            for idx, job in enumerate(other_india_jobs, 1):
                skills = ", ".join(job.get("tech_stack", [])[:4])
                md += f"### {idx}. [{job['title']}]({job['url']})\n"
                md += f"- **Company:** {job['company']} | **Match Score:** `{job.get('match_score')}/100`\n"
                md += f"- **Location:** {job.get('detected_city', job['location'])} | **Exp:** {job.get('experience')}\n"
                md += f"- **Tech:** {skills}\n"
                md += f"- **Why:** _{job.get('reason')}_\n\n"
    else:
        md += "### 📋 No direct openings passed the strict 24-hour India filter today.\n"
        md += "Apply directly via the 1-click verified feeds below.\n\n"

    md += "---\n\n### 🔗 Verified 1-Click Search Feeds (Past 24 Hours / 1–3 YOE)\n\n"
    md += "**Bhubaneswar:**\n"
    md += "- [Naukri: Java & Spring Boot in Bhubaneswar](https://www.naukri.com/java-spring-boot-jobs-in-bhubaneswar?experience=1)\n"
    md += "- [LinkedIn: Spring Boot Developer in Bhubaneswar (24h)](https://www.linkedin.com/jobs/search/?keywords=Spring%20Boot&location=Bhubaneswar%2C%20Odisha%2C%20India&f_TPR=r86400)\n\n"
    md += "**Pan-India (Remote / Hybrid / Hubs):**\n"
    md += "- [LinkedIn: All India Spring Boot (24h)](https://www.linkedin.com/jobs/search/?keywords=Spring%20Boot&location=India&f_TPR=r86400)\n"
    md += "- [Instahyre: Startups Hiring Java/Spring Boot](https://www.instahyre.com/search-jobs/?job_functions=software-engineering&skills=Java,Spring%20Boot)\n"
    md += "- [Hirist: Java Backend & Microservices India](https://www.hirist.tech/k/spring-boot-jobs)\n"

    return md

def send_digest_email(md_content):
    today = datetime.now().strftime("%Y-%m-%d")
    msg = MIMEMultipart("mixed")
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = f"🎯 [India 24H Digest] Java & Spring Boot Roles — {today}"

    html_content = markdown.markdown(md_content)
    styled_html = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1a1a1a; max-width: 740px; margin: auto; padding: 25px;">
        {html_content}
      </body>
    </html>
    """
    msg.attach(MIMEText(styled_html, "html"))

    filename = f"java_jobs_india_{today}.md"
    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(md_content.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header("Content-Disposition", f"attachment; filename={filename}")
    msg.attach(attachment)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
    print("Email sent successfully!")

if __name__ == "__main__":
    print("Collecting 24h India postings...")
    all_raw = []
    all_raw.extend(fetch_india_curated_rss())
    all_raw.extend(fetch_india_tech_feed())

    unique_candidates = {j["url"]: j for j in all_raw if j.get("url")}.values()
    print(f"Total candidate listings after initial filter: {len(unique_candidates)}")

    evaluated_matches = []
    for candidate in unique_candidates:
        result = score_and_enrich_job(candidate)
        if result:
            evaluated_matches.append(result)

    print(f"Final scored India-valid matches: {len(evaluated_matches)}")
    digest = build_markdown_report(evaluated_matches)
    send_digest_email(digest)