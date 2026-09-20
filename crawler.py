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

def fetch_google_jobs_rss():
    """Fetches real-time Java/Spring Boot jobs indexed strictly in India in the past 24 hours."""
    queries = [
        '("Java" OR "Spring Boot") ("Bhubaneswar" OR "Odisha") when:1d',
        '("Spring Boot") (developer OR engineer) (India OR Bangalore OR Hyderabad OR Pune) when:1d',
        '("Java" AND "Spring Boot") (fintech OR payments OR backend) India when:1d'
    ]
    
    discovered = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for q in queries:
        # Strict geo-locking to India (gl=IN, hl=en-IN)
        feed_url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            res = requests.get(feed_url, headers=headers, timeout=12)
            if res.status_code == 200:
                root = ET.fromstring(res.content)
                for item in root.findall(".//item"):
                    title = item.find("title").text if item.find("title") is not None else ""
                    link = item.find("link").text if item.find("link") is not None else ""
                    desc = item.find("description").text if item.find("description") is not None else ""
                    
                    comp = "Tech Organization"
                    clean_title = title
                    if " - " in title:
                        parts = title.rsplit(" - ", 1)
                        clean_title = parts[0]
                        comp = parts[1]

                    # Drop obvious foreign locations
                    foreign_markers = ["australia", "zealand", "nigeria", "united kingdom", "mexico", "canada", "washington", "metropolitan area"]
                    if any(marker in clean_title.lower() or marker in desc.lower() for marker in foreign_markers):
                        continue

                    # Filter for technical relevance
                    if any(k in clean_title.lower() for k in ["java", "spring", "backend", "software", "developer", "sde"]):
                        discovered.append({
                            "title": clean_title,
                            "company": comp,
                            "url": link,
                            "content": re.sub(r'<[^>]+>', ' ', desc)[:1200],
                            "location": "Bhubaneswar / India / Remote"
                        })
        except Exception as e:
            print(f"Feed error for query '{q}': {e}")

    return discovered

def fetch_open_tech_feed():
    """Secondary feed for real-time remote/hybrid software roles."""
    jobs = []
    url = "https://jobicy.com/api/v2/remote-jobs?count=20&tag=java"
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if res.status_code == 200:
            for item in res.json().get("jobs", []):
                jobs.append({
                    "title": item.get("jobTitle", "Java Engineer"),
                    "company": item.get("companyName", "Tech Org"),
                    "url": item.get("url"),
                    "content": re.sub(r'<[^>]+>', ' ', item.get("jobDescription", ""))[:1200],
                    "location": item.get("jobGeo", "India / Remote")
                })
    except Exception as e:
        print(f"Tech feed error: {e}")
    return jobs

def score_and_enrich_job(job):
    """Evaluates and matches candidate background using Gemini with token optimization."""
    if not GEMINI_API_KEY:
        return None

    title_lower = job['title'].lower()
    if any(disqualifier in title_lower for disqualifier in ["frontend", "react", "angular", "intern", "staff", "principal", "qa", "devops", "ios", "android"]):
        return None

    response_schema = {
        "type": "object",
        "properties": {
            "fit": {"type": "boolean"},
            "match_score": {"type": "integer"},
            "experience": {"type": "string"},
            "city_location": {"type": "string"},
            "is_bhubaneswar": {"type": "boolean"},
            "tech_stack": {
                "type": "array",
                "items": {"type": "string"}
            },
            "short_reason": {"type": "string"}
        },
        "required": ["fit", "match_score", "experience", "city_location", "is_bhubaneswar", "tech_stack", "short_reason"]
    }

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",  # Changed from gemini-1.5-flash as its depricated
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": response_schema,
            "temperature": 0.1
        }
    )

    prompt = f"""
Evaluate this job opening for a Java Backend Engineer (1-3 YOE).
Candidate Strengths: Java, Spring Boot, Microservices, PostgreSQL, Redis, GCP Pub/Sub, Distributed Caching, Fintech (BBPS, ISO 8583, HSM/TR-31, AutoPay, Idempotency).
Location Preference: Bhubaneswar (Odisha) is preferred highest, followed by Remote/Hybrid or any India tech hub.

Rules:
- fit: true if backend role using Java or Spring Boot.
- fit: false if strictly >4 YOE required, non-backend, or non-JVM stack (Python/Node/Go only).
- is_bhubaneswar: true if title/description mentions Bhubaneswar or Odisha.
- match_score: 90-100 for Bhubaneswar or Fintech/Payments Java roles; 75-89 for Spring Boot microservices/caching; 60-74 for general Java backend.
- short_reason: max 12 words highlighting why it matches.

Listing:
Title: {job['title']} | Source/Company: {job['company']}
Details: {job['content']}
"""

    try:
        response = model.generate_content(prompt)
        data = json.loads(response.text)
        if data.get("fit") and data.get("match_score", 0) >= 60:
            return {**job, **data}
    except Exception as e:
        print(f"Scoring error for {job['title']}: {e}")

    return None

def build_markdown_report(matched_jobs):
    today = datetime.now().strftime("%Y-%m-%d")
    md = f"# 🚀 Fresh Java & Spring Boot Job Alerts (Past 24 Hours) — {today}\n\n"
    md += f"_Real-time search across India with priority for Bhubaneswar, Remote, and High-Match Spring Boot roles._\n\n"
    md += "---\n\n"

    if matched_jobs:
        # Sort: Bhubaneswar roles first, then by match_score descending
        sorted_jobs = sorted(
            matched_jobs, 
            key=lambda x: (x.get("is_bhubaneswar", False), x.get("match_score", 0)), 
            reverse=True
        )

        bhubaneswar_jobs = [j for j in sorted_jobs if j.get("is_bhubaneswar")]
        other_jobs = [j for j in sorted_jobs if not j.get("is_bhubaneswar")]

        if bhubaneswar_jobs:
            md += "## 📍 Bhubaneswar & Odisha Local Openings\n\n"
            for idx, job in enumerate(bhubaneswar_jobs, 1):
                skills = ", ".join(job.get("tech_stack", [])[:4])
                md += f"### {idx}. [{job['title']}]({job['url']})\n"
                md += f"- **Company / Source:** {job['company']} | **Score:** `{job.get('match_score')}/100`\n"
                md += f"- **Location:** 📍 **{job.get('city_location', 'Bhubaneswar')}** | **Exp:** {job.get('experience')}\n"
                md += f"- **Tech:** {skills}\n"
                md += f"- **Match:** _{job.get('short_reason')}_\n\n"

        if other_jobs:
            md += "## 🌐 All-India & Remote / Hybrid Openings (Ranked by Score)\n\n"
            for idx, job in enumerate(other_jobs, 1):
                skills = ", ".join(job.get("tech_stack", [])[:4])
                md += f"### {idx}. [{job['title']}]({job['url']})\n"
                md += f"- **Company / Source:** {job['company']} | **Score:** `{job.get('match_score')}/100`\n"
                md += f"- **Location:** {job.get('city_location', 'India')} | **Exp:** {job.get('experience')}\n"
                md += f"- **Tech:** {skills}\n"
                md += f"- **Match:** _{job.get('short_reason')}_\n\n"
    else:
        md += "### 📋 No direct automated matches parsed in the last 24-hour cycle.\n"
        md += "Use the direct 1-click live filters below for real-time applications.\n\n"

    md += "---\n\n### 🔗 Live 1-Click Search Feeds (Last 24 Hours / 1–3 YOE)\n\n"
    md += "**Bhubaneswar Focus:**\n"
    md += "- [Naukri: Java / Spring Boot in Bhubaneswar (Past 24h)](https://www.naukri.com/java-spring-boot-jobs-in-bhubaneswar?experience=1)\n"
    md += "- [LinkedIn Jobs: Spring Boot Developer in Bhubaneswar (Past 24h)](https://www.linkedin.com/jobs/search/?keywords=Spring%20Boot&location=Bhubaneswar%2C%20Odisha%2C%20India&f_TPR=r86400)\n\n"
    md += "**All-India & High-Growth Tech:**\n"
    md += "- [LinkedIn Jobs: All India Spring Boot (Past 24h)](https://www.linkedin.com/jobs/search/?keywords=Spring%20Boot&location=India&f_TPR=r86400)\n"
    md += "- [Instahyre: Startups Hiring Java Backend](https://www.instahyre.com/search-jobs/?job_functions=software-engineering&skills=Java,Spring%20Boot)\n"
    md += "- [Hirist: Java & Spring Boot Microservices](https://www.hirist.tech/k/spring-boot-jobs)\n"
    md += "- [Indeed India: Spring Boot (Past 24h)](https://in.indeed.com/jobs?q=Spring+Boot&l=India&fromage=1)\n"

    return md

def send_digest_email(md_content):
    today = datetime.now().strftime("%Y-%m-%d")
    msg = MIMEMultipart("mixed")
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = f"🎯 [24H Digest] Java & Spring Boot Openings — {today}"

    html_content = markdown.markdown(md_content)
    styled_html = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1a1a1a; max-width: 740px; margin: auto; padding: 25px;">
        {html_content}
      </body>
    </html>
    """
    msg.attach(MIMEText(styled_html, "html"))

    filename = f"java_jobs_24h_{today}.md"
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
    print("Fetching fresh 24-hour job postings...")
    all_raw = []
    all_raw.extend(fetch_google_jobs_rss())
    all_raw.extend(fetch_open_tech_feed())

    # Deduplicate by URL within the same run
    unique_candidates = {j["url"]: j for j in all_raw if j.get("url")}.values()
    print(f"Total raw listings fetched: {len(unique_candidates)}")

    evaluated_matches = []
    for candidate in unique_candidates:
        result = score_and_enrich_job(candidate)
        if result:
            evaluated_matches.append(result)

    print(f"Matched & Scored {len(evaluated_matches)} relevant openings.")
    digest = build_markdown_report(evaluated_matches)
    send_digest_email(digest)