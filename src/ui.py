"""Look and feel for the Streamlit app (src/app.py): CSS, badges, page headers and charts.

Pure presentation. Nothing here reads or changes data.
"""
import altair as alt
import pandas as pd
import streamlit as st

BLUE, GREEN, AMBER, RED, GREY = "#2F5BEA", "#1F9D6B", "#E8A317", "#D64545", "#8A94A6"

CSS = """
<style>
.block-container {padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1400px;}
footer {visibility: hidden;}
h1, h2, h3 {letter-spacing: -0.01em;}
[data-testid="stMetric"] {background: #FFFFFF; border: 1px solid #E3E8EF; border-radius: 10px;
    padding: 14px 16px; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.06);}
[data-testid="stMetricLabel"] {color: #5B6577;}
[data-testid="stMetricValue"] {font-size: 1.55rem; font-weight: 650;}
[data-testid="stSidebar"] {border-right: 1px solid #E3E8EF;}
.brand {font-size: 1.25rem; font-weight: 700; color: #1B2430; margin-bottom: 0.1rem;}
.brand span {color: #2F5BEA;}
.tagline {font-size: 0.8rem; color: #5B6577; margin-bottom: 0.9rem;}
.page-head {border-bottom: 1px solid #E3E8EF; padding-bottom: 0.7rem; margin-bottom: 1.1rem;}
.page-head .t {font-size: 1.75rem; font-weight: 700; color: #1B2430; line-height: 1.2;}
.page-head .s {font-size: 0.93rem; color: #5B6577; margin-top: 0.15rem;}
.pill {display: inline-block; padding: 2px 11px; border-radius: 999px; font-size: 0.76rem; font-weight: 650;
    margin-right: 6px; letter-spacing: 0.02em; text-transform: uppercase;}
.pill.open {background: #FFF4D6; color: #8A5A00;}
.pill.in_review {background: #E3EBFF; color: #1E3FA8;}
.pill.closed {background: #E8EBF0; color: #4A5568;}
.pill.high {background: #FDE4E4; color: #A12626;}
.pill.medium {background: #FFF1D6; color: #8A5A00;}
.pill.low {background: #DDF5EA; color: #11694A;}
.pill.pass {background: #DDF5EA; color: #11694A;}
.pill.fail {background: #FDE4E4; color: #A12626;}
.pill.info {background: #E3EBFF; color: #1E3FA8;}
.case-head {background: #F7F9FC; border: 1px solid #E3E8EF; border-radius: 12px; padding: 16px 20px; margin: 0.4rem 0 1rem 0;}
.case-head .id {font-size: 1.15rem; font-weight: 700; color: #1B2430;}
.case-head .who {color: #5B6577; font-size: 0.92rem; margin: 2px 0 10px 0;}
.hint {color: #5B6577; font-size: 0.85rem;}
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def sidebar_brand():
    st.markdown('<div class="brand">Fraud Alert <span>Triage</span></div>'
                '<div class="tagline">Analyst workbench. Synthetic data only.</div>', unsafe_allow_html=True)


def page_header(title, subtitle=""):
    sub = f'<div class="s">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="page-head"><div class="t">{title}</div>{sub}</div>', unsafe_allow_html=True)


def level(score):
    score = int(score)
    return "high" if score >= 70 else "medium" if score >= 45 else "low"


def pill(text, kind):
    return f'<span class="pill {kind}">{text}</span>'


def status_pill(status):
    return pill(str(status).replace("_", " "), status if status in ("open", "in_review", "closed") else "info")


def priority_pill(score):
    return pill(f"{level(score)} priority {int(score)}", level(score))


def _frame(series, name="value"):
    df = series.rename(name).reset_index()
    df.columns = ["label", "value"]
    df["label"] = df["label"].astype(str)
    return df


def bars(series, color=BLUE, horizontal=True, height=None):
    """Bar chart of a pandas Series (index = category, value = count)."""
    df = _frame(series)
    base = alt.Chart(df)
    tip = [alt.Tooltip("label:N", title=""), alt.Tooltip("value:Q", title="count")]
    if horizontal:
        y = alt.Y("label:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260))
        bar = base.mark_bar(color=color, cornerRadiusEnd=3).encode(x=alt.X("value:Q", title=None), y=y, tooltip=tip)
        txt = base.mark_text(align="left", dx=4, color="#5B6577").encode(x="value:Q", y=y, text="value:Q")
        chart = (bar + txt).properties(height=height or max(120, 34 * len(df)))
    else:
        x = alt.X("label:N", sort=None, title=None, axis=alt.Axis(labelAngle=0))
        bar = base.mark_bar(color=color, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(x=x, y=alt.Y("value:Q", title=None), tooltip=tip)
        chart = bar.properties(height=height or 240)
    st.altair_chart(chart.configure_view(strokeWidth=0).configure_axis(grid=False, domain=False, ticks=False), width="stretch")


def breakdown_chart(bd):
    """Score breakdown: points per factor, blue for added points, green for mitigating points."""
    df = bd.copy()
    df["factor"] = df["factor"].astype(str).str.replace("_", " ")
    df["points"] = df["points"].astype(int)
    y = alt.Y("factor:N", sort=None, title=None, axis=alt.Axis(labelLimit=260))
    bar = alt.Chart(df).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("points:Q", title=None), y=y,
        color=alt.condition(alt.datum.points >= 0, alt.value(BLUE), alt.value(GREEN)),
        tooltip=[alt.Tooltip("factor:N", title=""), alt.Tooltip("points:Q")])
    txt = alt.Chart(df).mark_text(align="left", dx=4, color="#5B6577").encode(x="points:Q", y=y, text="points:Q")
    chart = (bar + txt).properties(height=max(110, 30 * len(df)))
    st.altair_chart(chart.configure_view(strokeWidth=0).configure_axis(grid=False, domain=False, ticks=False), width="stretch")
