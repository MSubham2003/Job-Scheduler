import os
import json
import smtplib
import subprocess
import requests
import markdown
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

DB_FILE = "seen_jobs.json"

# Curated list of high-growth tech & fintech companies
TARGET_BOARDS = {
    "greenhouse": [
        "razorpay", "cred", "swiggy", "postman", "branchmetrics", 
        "airmeet", "browserstack", "clevertap", "urbancompany", "zepto"
    ],
    "lever": [
        "juspay", "setu", "decentro", "sliceit", "groww", 
        "fi-money", "kreditbee", "paytmbank"
    ]
}

PROFILE_CRITERIA = """
[CANDIDATE ARCHETYPE]
- Role: Java Backend Engineer / Core Systems Engineer
- Experience Band: 1 - 3 Years (Targeting: SDE 1, SDE 2, Software Engineer, Backend Engineer)
- Primary Language & Frameworks: Java, Spring Boot, Spring Data JPA, RESTful Microservices[cite: 1]

[TECHNICAL FOUNDATIONS & INFRASTRUCTURE]
- Persistence & Caching: PostgreSQL, Redis (distributed caching, token caching, asynchronous refresh, cache invalidation)[cite: 1]
- Distributed Systems & Messaging: Event-driven architecture, Google Cloud Pub/Sub, message retries, async processing, dead-letter pipelines[cite: 1]
- Cloud & Analytics: GCP (Cloud Logging, Secret Manager, Pub/Sub, BigQuery ETL/ingestion pipelines)[cite: 1]
- Reliability & Performance: Distributed payment orchestration, idempotency controls, transaction retries, distributed tracing (UUID-based), high-throughput batch/paginated processing[cite: 1]

[SPECIALIZED DOMAIN STRENGTHS (FINTECH & SECURE SYSTEMS)]
- Payment Standards: BBPS (COU & BOU workflows), ISO 8583 payment messaging, AutoPay scheduling[cite: 1]
- Hardware Security & Cryptography: HSM integrations, TR-31 key exchange, PIN verification, ZPK/ZAK lifecycle management, AES/RSA symmetric & asymmetric encryption, SSL/TLS, JKS keystores[cite: 1]
- High-Volume Ingestion: Parsing bulk payment datasets, asynchronous reconciliation, switch invocation, NPCI routing integration[cite: 1]

[EVALUATION RULES & HARD CONSTRAINTS]
1. HARD DISQUALIFIERS (Set "fit": false, "match_score": 0):
   - Strict experience requirement > 4 years (e.g., Senior, Lead, Staff, Principal, Architect).
   - Non-backend roles (Pure Frontend, React/Angular-only, Android/iOS, Manual QA, SDET, pure DevOps/SRE, Data Science).
   - Backend roles strictly requiring non-Java stacks (e.g., Python/Django only, Node.js only, Go/Rust only) with no Java/JVM footprint.
   - Unpaid internships or non-engineering listings (DevRel, Tech Support, Operations).

2. HIGH-FIT SIGNALS (Score >= 80):
   - Core Java / Spring Boot backend microservices.
   - Distributed systems focusing on concurrency, caching (Redis), relational databases (PostgreSQL), and message queues (Pub/Sub/Kafka/RabbitMQ)[cite: 1].
   - Fintech, banking, payment gateways, wallets, or transaction security.

3. FLEXIBLE CONSIDERATION (Score 65 - 79):
   - General backend engineering roles in high-scale domains (E-Commerce, Logistics, SaaS) where core requirements center on Java microservices, API architecture, and database design.
"""

def load_seen_ids():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen_ids(seen_ids):
    with open(DB_FILE, "w") as f:
        json.dump(list(seen_ids), f, indent=2)

def fetch_greenhouse_jobs(company):
    jobs = []
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for item in data.get("jobs", []):
                title = item.get("title", "")
                loc = item.get("location", {}).get("name", "")
                # Fast keyword pre-filter
                if any(k in title.lower() for k in ["backend", "java", "software", "sde", "engineer"]):
                    jobs.append({
                        "id": f"gh_{item['id']}",
                        "company": company.capitalize(),
                        "title": title,
                        "location": loc,
                        "url": item.get("absolute_url"),
                        "content": item.get("content", "")[:3500]
                    })
    except Exception as e:
        print(f"Greenhouse fetch error for {company}: {e}")
    return jobs

def fetch_lever_jobs(company):
    jobs = []
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            for item in res.json():
                title = item.get("text", "")
                categories = item.get("categories", {})
                loc = categories.get("location", "")
                if any(k in title.lower() for k in ["backend", "java", "software", "sde", "engineer"]):
                    jobs.append({
                        "id": f"lev_{item['id']}",
                        "company": company.capitalize(),
                        "title": title,
                        "location": loc,
                        "url": item.get("hostedUrl"),
                        "content": item.get("descriptionPlain", "")[:3500]
                    })
    except Exception as e:
        print(f"Lever fetch error for {company}: {e}")
    return jobs

def score_job_with_gemini(job):
    if not GEMINI_API_KEY:
        return None

    # 1. Fast pre-filter: Skip API calls entirely for obvious non-backend roles
    title_lower = job['title'].lower()
    disqualified_keywords = ["frontend", "react", "angular", "ios", "android", "intern", "staff", "principal", "qa", "devops"]
    if any(k in title_lower for k in disqualified_keywords):
        return None

    # 2. Trim job content to 1,500 chars (removes footer boilerplate & saves input tokens)
    clean_content = " ".join(job['content'].split())[:1500]

    # 3. Native schema definition (guarantees valid JSON without prompting tokens)
    response_schema = {
        "type": "object",
        "properties": {
            "fit": {"type": "boolean"},
            "match_score": {"type": "integer"},
            "experience": {"type": "string"},
            "key_overlap": {
                "type": "array",
                "items": {"type": "string"}
            },
            "reason": {"type": "string"}
        },
        "required": ["fit", "match_score", "experience", "key_overlap", "reason"]
    }

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": response_schema,
            "temperature": 0.1
        }
    )

    # 4. Dense, token-optimized prompt
    prompt = f"""
    Candidate: Java Backend Engineer (1-3 YOE).
    Core: Java, Spring Boot, Microservices, PostgreSQL, Redis, GCP Pub/Sub.
    Domain Strengths: Fintech, BBPS, ISO 8583, HSM/TR-31, distributed idempotency, payment orchestration.
    Rules:
    - fit = false if >4 YOE required, non-backend, or strictly non-Java (Node/Python/Go only).
    - match_score: 80-100 for Java microservices/Fintech; 65-79 for Java SaaS/E-commerce backend; <65 otherwise.
    - reason: strictly max 15 words.

    Listing:
    Company: {job['company']} | Title: {job['title']} | Location: {job['location']}
    Description: {clean_content}
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
    md = f"# 🚀 Tailored Java Backend Job Alert — {today}\n\n"
    md += f"_Automated direct-ATS crawler verified against your fintech & Java/Spring Boot profile._\n\n"
    md += "---\n\n"

    if matched_jobs:
        sorted_jobs = sorted(matched_jobs, key=lambda x: x.get("match_score", 0), reverse=True)
        for idx, job in enumerate(sorted_jobs, 1):
            score = job.get("match_score")
            skills = ", ".join(job.get("key_overlap", []))
            md += f"### {idx}. [{job['title']} @ {job['company']}]({job['url']})\n"
            md += f"- **Match Score:** `{score}/100` | **Exp:** {job.get('experience')} | **Location:** {job.get('location')}\n"
            md += f"- **Relevant Tech:** {skills}\n"
            md += f"- **Why Apply:** {job.get('reason')}\n\n"
    else:
        md += "### 📋 No New Unseen Roles Found Today\n"
        md += "All existing postings across monitored company boards have already been delivered.\n\n"

    md += "---\n\n### 🔗 Instant 1-Click Search Feeds (Filtered for Java / Spring Boot 1–3 YOE)\n\n"
    md += "**General & Enterprise Portals:**\n"
    md += "- [Naukri (Java + Spring Boot, 1–3 YOE, India)](https://www.naukri.com/java-spring-boot-jobs-in-india?experience=1)\n"
    md += "- [LinkedIn Jobs (Spring Boot, India, Past 24 Hours)](https://www.linkedin.com/jobs/search/?keywords=Spring%20Boot&location=India&f_TPR=r86400)\n"
    md += "- [Indeed India (Spring Boot Developer, Past 3 Days)](https://in.indeed.com/jobs?q=Spring+Boot&l=India&fromage=3)\n\n"

    md += "**Premium Tech & Startup Portals:**\n"
    md += "- [Hirist (Tech-Focused: Java & Spring Boot Microservices)](https://www.hirist.tech/k/spring-boot-jobs)\n"
    md += "- [Instahyre (Curated Startup Matches: Java & Spring Boot)](https://www.instahyre.com/search-jobs/?job_functions=software-engineering&skills=Java,Spring%20Boot)\n"
    md += "- [Wellfound / AngelList (Early-Stage to Series B Backend Roles)](https://wellfound.com/role/l/backend-engineer/india)\n"
    md += "- [Cutshort (Direct Recruiter Chat: Java Backend Engineer)](https://cutshort.io/jobs/java-developer-jobs)\n"
    md += "- [Hasjob (Community & High-Growth Startups: Java)](https://hasjob.co/?q=Java)\n\n"

    md += "**Global & Remote-First Tech:**\n"
    md += "- [Jobicy (Remote Java Software Engineer Openings)](https://jobicy.com/jobs/remote-java-jobs)\n"
    return md

def send_digest_email(md_content):
    today = datetime.now().strftime("%Y-%m-%d")
    msg = MIMEMultipart("mixed")
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = f"⚡ Daily Java & Fintech Openings — {today}"

    html_content = markdown.markdown(md_content)
    styled_html = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1a1a1a; max-width: 740px; margin: auto; padding: 25px;">
        {html_content}
      </body>
    </html>
    """
    msg.attach(MIMEText(styled_html, "html"))

    # Attach MD file
    filename = f"java_jobs_{today}.md"
    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(md_content.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header("Content-Disposition", f"attachment; filename={filename}")
    msg.attach(attachment)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
    print("Email successfully sent!")

if __name__ == "__main__":
    seen_ids = load_seen_ids()
    print(f"Loaded {len(seen_ids)} previously indexed jobs.")

    unfiltered_candidates = []
    # Fetch directly from official ATS APIs
    for co in TARGET_BOARDS["greenhouse"]:
        unfiltered_candidates.extend(fetch_greenhouse_jobs(co))
    for co in TARGET_BOARDS["lever"]:
        unfiltered_candidates.extend(fetch_lever_jobs(co))

    # Deduplicate against previous runs
    new_jobs = [j for j in unfiltered_candidates if j["id"] not in seen_ids]
    print(f"Discovered {len(new_jobs)} unseen technical postings across monitored boards.")

    matched_jobs = []
    for j in new_jobs:
        evaluated = score_job_with_gemini(j)
        if evaluated:
            matched_jobs.append(evaluated)
        # Mark as seen so you never get duplicate alerts
        seen_ids.add(j["id"])

    save_seen_ids(seen_ids)
    report_md = build_markdown_report(matched_jobs)
    send_digest_email(report_md)