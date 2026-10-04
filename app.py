import re
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

def ask_question(question):
    text = question.lower()
    year_match = re.search(r"20(1[0-4])", text)
    year = int(year_match.group(0)) if year_match else 2014
    amount_match = re.search(r"(\d{3,})", text.replace(",", ""))
    amount = float(amount_match.group(1)) if amount_match else 5000

    if "more than" in text or "greater than" in text or "over" in text:
        if "employee" in text or "who" in text or "spent" in text:
            sql = """
                SELECT FullName, ROUND(SUM(Amount), 2) AS TotalSpent
                FROM pcards
                WHERE Year = ? AND Amount > 0
                GROUP BY FullName
                HAVING SUM(Amount) > ?
                ORDER BY TotalSpent DESC
                LIMIT 100
            """
            return sql, pd.read_sql_query(sql, get_connection(), params=(year, amount))
        sql = """
            SELECT Amount, FullName, Vendor, Description, TransactionDate, MCC
            FROM pcards
            WHERE Year = ? AND Amount > ?
            ORDER BY Amount DESC
            LIMIT 100
        """
        return sql, pd.read_sql_query(sql, get_connection(), params=(year, amount))

    if "vendor" in text or "merchant" in text:
        words = re.findall(r"[a-z]{4,}", text)
        stop = {"vendor", "merchant", "which", "what", "from", "with", "that", "this", "show", "find", "purchases", "purchase", "transactions", "year"}
        keyword = next((word for word in words if word not in stop), "")
        if not keyword:
            raise ValueError("Name the vendor, for example: purchases from shell in 2014.")
        sql = """
            SELECT Amount, FullName, Vendor, Description, TransactionDate, MCC
            FROM pcards
            WHERE Year = ? AND LOWER(Vendor) LIKE '%' || ? || '%'
            ORDER BY Amount DESC
            LIMIT 100
        """
        return sql, pd.read_sql_query(sql, get_connection(), params=(year, keyword))

    words = re.findall(r"[a-z]{4,}", text)
    stop = {"which", "what", "from", "with", "that", "this", "show", "find", "purchases", "purchase", "transactions", "description", "about", "year"}
    keyword = next((word for word in words if word not in stop), "")
    if not keyword:
        raise ValueError("Try: employees who spent more than 50000 in 2014. Or: purchases mentioning alcohol in 2014.")
    sql = """
        SELECT Amount, FullName, Vendor, Description, TransactionDate, MCC
        FROM pcards
        WHERE Year = ?
          AND (LOWER(Description) LIKE '%' || ? || '%' OR LOWER(MCC) LIKE '%' || ? || '%')
        ORDER BY Amount DESC
        LIMIT 100
    """
    return sql, pd.read_sql_query(sql, get_connection(), params=(year, keyword, keyword))

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
    st.write("Examples: employees who spent more than 50000 in 2014. Transactions over 5000 in 2014. Purchases mentioning alcohol in 2014. Purchases from shell in 2014.")
    question = st.text_area("Question", "Which employees spent more than 50000 in 2014?")
    if st.button("Ask"):
        try:
            sql, rows = ask_question(question)
            st.code(sql, language="sql")
            st.dataframe(rows, use_container_width=True)
        except Exception as error:
            st.error(str(error))
