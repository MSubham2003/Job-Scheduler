import os
import smtplib
import requests
import markdown
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

def fetch_jobs():
    """Fetch recent Java and Spring Boot roles."""
    query_url = "https://jobicy.com/api/v2/remote-jobs?count=30&tag=java"
    headers = {"User-Agent": "Mozilla/5.0"}
    jobs = []
    
    try:
        res = requests.get(query_url, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            raw_jobs = data.get("jobs", [])
            for item in raw_jobs:
                title = item.get("jobTitle", "")
                company = item.get("companyName", "N/A")
                url = item.get("url", "#")
                geo = item.get("jobGeo", "Anywhere / Hybrid")
                
                # Filter for Java / Backend / Spring Boot relevance
                if any(k in title.lower() for k in ["java", "spring", "backend", "software"]):
                    jobs.append({
                        "title": title,
                        "company": company,
                        "url": url,
                        "geo": geo
                    })
    except Exception as e:
        print(f"Error fetching API jobs: {e}")

    return jobs

def build_curated_portals():
    """Permanent direct search links for top India tech portals."""
    return [
        {"portal": "Naukri (Java + Spring Boot, 1-3 YOE)", "url": "https://www.naukri.com/java-spring-boot-jobs-in-india?experience=1"},
        {"portal": "Instahyre (Java Backend Startups)", "url": "https://www.instahyre.com/search-jobs/?job_functions=software-engineering&skills=Java,Spring%20Boot"},
        {"portal": "Wellfound / AngelList (Early-stage & Unicorns)", "url": "https://wellfound.com/role/l/backend-engineer/india"},
        {"portal": "LinkedIn Jobs (India, Past 24h)", "url": "https://www.linkedin.com/jobs/search/?keywords=Spring%20Boot&location=India&f_TPR=r86400"},
        {"portal": "Hasjob (Product & Tech Startups)", "url": "https://hasjob.co/?q=Java"}
    ]

def generate_markdown(jobs, portals):
    today = datetime.now().strftime("%Y-%m-%d")
    md = f"# Daily Java & Spring Boot Job Digest — {today}\n\n"
    
    md += "### Active Job Postings\n\n"
    if jobs:
        for idx, j in enumerate(jobs[:15], 1):
            md += f"{idx}. **[{j['title']}]({j['url']})** at **{j['company']}** ({j['geo']})\n"
    else:
        md += "_No new postings picked up by API today. Check the direct feeds below._\n"
        
    md += "\n---\n\n### Instant One-Click Live Feeds (Filtered for 0–3 YOE)\n\n"
    for p in portals:
        md += f"- [{p['portal']}]({p['url']})\n"
        
    return md

def send_email(md_content):
    today = datetime.now().strftime("%Y-%m-%d")
    subject = f"🚀 Java & Spring Boot Daily Jobs Digest — {today}"
    
    msg = MIMEMultipart("mixed")
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = subject
    
    # HTML preview in body
    html_content = markdown.markdown(md_content)
    body_part = MIMEText(f"<html><body>{html_content}</body></html>", "html")
    msg.attach(body_part)
    
    # Markdown file attachment
    filename = f"java_jobs_{today}.md"
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
    jobs = fetch_jobs()
    portals = build_curated_portals()
    md_content = generate_markdown(jobs, portals)
    send_email(md_content)