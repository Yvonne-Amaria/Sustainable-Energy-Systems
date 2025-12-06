# ui_components.py
from __future__ import annotations

import streamlit as st
from typing import Callable, Iterable, Tuple


def feature_card(title: str, body: str, on_click: Callable | None = None, small: bool = False, key: str | None = None):
    """Reusable card with a unique button key to avoid duplicate element IDs."""
    with st.container(border=True):
        st.subheader(title) if not small else st.markdown(f"**{title}**")
        st.write(body)
        if on_click:
            btn_key = key or f"btn_open_{abs(hash(title))}"
            st.button("Open", on_click=on_click, key=btn_key, width="stretch")


def pill(title: str, body: str):
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(body)


def two_col_metrics(left_items: Iterable[Tuple[str, str]], right_items: Iterable[Tuple[str, str]]):
    c1, c2 = st.columns(2)
    with c1:
        for k, v in left_items:
            st.metric(k, v)
    with c2:
        for k, v in right_items:
            st.metric(k, v)


def user_inputs_panel(title: str, fields: Iterable[Tuple[str, str]]):
    with st.expander(title, expanded=True):
        out = {}
        for label, key in fields:
            out[key] = st.text_input(label, key=f"inp_{key}")
        return out


def note(msg: str):
    st.info(msg)

