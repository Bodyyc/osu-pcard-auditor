import json
import sqlite3
import urllib.request
from pathlib import Path

import pandas as pd
import streamlit as st

DB_URL = "https://github.com/Bodyyc/osu-pcard-auditor/releases/download/v1/pcards.db"
DB_PATH = Path("pcards.db")

st.set_page_config(page_title="OSU P-card audit", layout="wide")

def load_database():
    if not DB_PATH.exists():
        urllib.request.urlretrieve(DB_URL, DB_PATH)
    return sqlite3.connect(DB_PATH, check_same_thread=False)

@st.cache_resource
def get_connection():
    return load_database()

def search(year, field, keyword):
    column = "Description" if field == "description" else "Vendor"
    query = f"""
        SELECT Year, Month, FullName, Amount, Vendor, Description,
               TransactionDate, PostedDate, MCC
        FROM pcards
        WHERE Year = ?
          AND LOWER({column}) LIKE '%' || LOWER(?) || '%'
        ORDER BY Amount DESC
        LIMIT 200
    """
    return pd.read_sql_query(query, get_connection(), params=(int(year), keyword.strip()))

def safe_select(sql):
    text = sql.strip().strip("`")
    if text.lower().startswith("sql"):
        text = text[3:].strip()
    text = text.rstrip(";").strip()
    lowered = text.lower()
    if not lowered.startswith("select") or ";" in text:
        raise ValueError("Only one SELECT query is allowed.")
    banned = ("insert", "update", "delete", "drop", "alter", "attach", "pragma", "create")
    if any(word in lowered for word in banned):
        raise ValueError("That query is not allowed.")
    if "pcards" not in lowered:
        raise ValueError("The query must use the pcards table.")
    return f"SELECT * FROM ({text}) AS audit_q LIMIT 100"

def ask_question(question):
    api_key = st.secrets.get("XAI_API_KEY", "")
    if not api_key:
        raise ValueError("Add XAI_API_KEY in the host secrets. Do not put it in this file.")
    prompt = (
        "Write one SQLite SELECT for table pcards. Reply with SQL only. "
        "Columns: Year, Month, FullName, Description, Amount, Vendor, "
        "TransactionDate, PostedDate, MCC, CardholderLastName, CardholderFirstInitial. "
        "Dates look like 7/26/2014 0:00:00. Use Year = 2014 unless another year from 2010 to 2014 is named. "
        "Include LIMIT 100."
    )
    body = json.dumps({
        "model": "grok-4.5",
        "temperature": 0,
        "max_tokens": 350,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ],
    }).encode()
    request = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode())
    raw = payload["choices"][0]["message"]["content"]
    sql = safe_select(raw)
    return sql, pd.read_sql_query(sql, get_connection())

st.title("OSU P-card review")
st.caption("A match is a lead for follow-up, not proof of a violation.")
ask_tab, dashboard_tab = st.tabs(["Ask in plain language", "Prohibited purchases"])

with dashboard_tab:
    st.subheader("How to use this dashboard")
    st.markdown(
        """
        1. Choose the year. Use **2014** for the assignment.
        2. **Description search** checks only the description. Examples: alcohol, gift card, donation, membership, insurance, late fee, moving.
        3. **Vendor search** checks only the merchant. Examples: liquor, postal, shell, florist.
        4. Review the amount, employee, vendor, date, and merchant category before deciding there was a violation.
        """
    )
    years = pd.read_sql_query("SELECT DISTINCT Year FROM pcards ORDER BY Year", get_connection())
    year_list = years["Year"].tolist()
    year = st.selectbox("Year", year_list, index=year_list.index(2014) if 2014 in year_list else 0)

    left, right = st.columns(2)
    with left:
        st.subheader("Description search")
        description = st.text_input("Description keyword", value="alcohol")
        if st.button("Search descriptions"):
            rows = search(year, "description", description)
            st.write(f"{len(rows)} description matches for “{description}” in {year}")
            st.dataframe(rows, use_container_width=True)
    with right:
        st.subheader("Vendor search")
        vendor = st.text_input("Vendor keyword", value="postal")
        if st.button("Search vendors"):
            rows = search(year, "vendor", vendor)
            st.write(f"{len(rows)} vendor matches for “{vendor}” in {year}")
            st.dataframe(rows, use_container_width=True)

with ask_tab:
    st.subheader("Ask a question")
    st.write("The question is turned into a read-only query. At most 100 rows are shown. Check the SQL before relying on it.")
    question = st.text_area("Question", "Which employees spent more than 50000 in 2014? Show name and total.")
    if st.button("Ask"):
        try:
            sql, rows = ask_question(question)
            st.code(sql, language="sql")
            st.dataframe(rows, use_container_width=True)
        except Exception as error:
            st.error(str(error))
