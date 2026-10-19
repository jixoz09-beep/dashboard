import re

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# 원본 데이터 주소
POPULATION_URL = (
    "https://raw.githubusercontent.com/first2022-cyber/contents//main/"
    "population_ts_yearly_gender.zip"
)
GEOJSON_URL = (
    "https://raw.githubusercontent.com/first2022-cyber/contents//main/"
    "sigungu_kr.geojson"
)
TARGET_YEAR = "2026"


st.set_page_config(
    page_title="전국 고령화 단계구분도",
    page_icon="🗺️",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {
        background: #fffaf0;
    }
    h1, h2, h3 {
        color: #573d2b;
    }
    div[data-testid="stMetric"] {
        background: #fff3d6;
        border: 1px solid #f1dfb9;
        border-radius: 12px;
        padding: 12px 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def normalize_code(value) -> str:
    """지역 코드를 문자열로 통일한다."""
    if value is None or pd.isna(value):
        return ""

    code = str(value).strip()

    if code.endswith(".0"):
        code = code[:-2]

    if code.isdigit() and len(code) < 5:
        code = code.zfill(5)

    return code


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def load_population() -> pd.DataFrame:
    """인구 CSV를 읽어 2026년 시군구별 고령화율을 계산한다."""

    # ZIP 압축 CSV를 직접 읽는다.
    df = pd.read_csv(
        POPULATION_URL,
        compression="zip",
        dtype={"코드": "string"},
        low_memory=False,
    )

    df.columns = [str(column).strip() for column in df.columns]

    required = {"연도", "코드"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"인구 자료에 필요한 열이 없습니다: {', '.join(sorted(missing))}"
        )

    # 2026년 데이터만 선택한다.
    years = df["연도"].astype("string").str.extract(
        r"(\d{4})", expand=False
    )
    df = df.loc[years.eq(TARGET_YEAR)].copy()

    if df.empty:
        raise ValueError("인구 자료에서 2026년 데이터를 찾지 못했습니다.")

    # 전체 인구 계산에는 '계_'로 시작하는 열만 사용한다.
    # 남_ 및 여_ 열은 더하지 않는다.
    total_cols = [
        column
        for column in df.columns
        if column.startswith("계_")
    ]

    if not total_cols:
        raise ValueError(
            "'계_'로 시작하는 나이별 인구 열을 찾지 못했습니다."
        )

    # 65세 이상 인구 열을 선택한다.
    # '계_65세', '계_66세', ... '계_100세 이상'을 포함한다.
    senior_cols = []

    for column in total_cols:
        match = re.match(
            r"^계_(\d+)세\s*(?:이상)?$",
            column,
        )

        if match and int(match.group(1)) >= 65:
            senior_cols.append(column)

    if not senior_cols:
        raise ValueError(
            "'계_65세'부터 '계_100세 이상'까지의 열을 찾지 못했습니다."
        )

    # 인구 열을 숫자로 변환한다.
    df[total_cols] = (
        df[total_cols]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0)
    )

    # 동별 전체 인구와 65세 이상 인구를 계산한다.
    df["전체 인구"] = df[total_cols].sum(axis=1)
    df["65세 이상 인구"] = df[senior_cols].sum(axis=1)

    # 동 코드 앞 5자리를 시군구 코드로 사용한다.
    df["동코드_문자열"] = df["코드"].map(normalize_code).astype("string")
    df["시군구코드"] = df["동코드_문자열"].str[:5]

    df = df.loc[
        df["시군구코드"].notna()
        & df["시군구코드"].ne("")
    ].copy()

    # 시군구별 인구를 합산한다.
    grouped = (
        df.groupby("시군구코드", as_index=False)[
            ["65세 이상 인구", "전체 인구"]
        ]
        .sum()
    )

    # 고령화율 = 65세 이상 인구 / 전체 인구 × 100
    grouped["고령화율(%)"] = np.where(
        grouped["전체 인구"] > 0,
        grouped["65세 이상 인구"]
        / grouped["전체 인구"]
        * 100,
        np.nan,
    )

    return grouped


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def load_geojson() -> dict:
    """requests로 GeoJSON을 내려받고 코드 형식을 통일한다."""

    response = requests.get(
        GEOJSON_URL,
        timeout=60,
    )
    response.raise_for_status()

    geojson = response.json()

    if (
        not isinstance(geojson, dict)
        or not isinstance(geojson.get("features"), list)
    ):
        raise ValueError("시군구 GeoJSON 형식이 올바르지 않습니다.")

    for feature in geojson["features"]:
        properties = feature.setdefault("properties", {})

        properties["코드"] = normalize_code(
            properties.get("코드")
        )

    return geojson


def build_map_data(
    geojson: dict,
    population_stats: pd.DataFrame,
) -> pd.DataFrame:
    """시군구 이름이 아닌 코드로 인구 데이터와 경계를 결합한다."""

    geo_rows = []

    for feature in geojson["features"]:
        properties = feature.get("properties", {})

        code = normalize_code(properties.get("코드"))

        if not code:
            continue

        geo_rows.append(
            {
                "코드": code,
                "시군구": properties.get("시군구", "이름 없음"),
                "시도": properties.get("시도", ""),
            }
        )

    geo_meta = pd.DataFrame(geo_rows)

    if geo_meta.empty:
        raise ValueError(
            "GeoJSON에서 시군구 코드 정보를 찾지 못했습니다."
        )

    geo_meta = geo_meta.drop_duplicates(subset=["코드"])

    stats = population_stats.copy()
    stats["시군구코드"] = (
        stats["시군구코드"].map(normalize_code)
    )

    # 지역명 대신 문자열 코드로 결합한다.
    map_df = geo_meta.merge(
        stats,
        left_on="코드",
        right_on="시군구코드",
        how="left",
    )

    return map_df


# -----------------------------
# 화면 구성
# -----------------------------

st.title("🗺️ 전국 고령화 단계구분도")

st.write(
    "2026년 6월 인구 자료를 이용해 "
    "전국 시군구별 65세 이상 인구 비율을 확인합니다. "
    "색이 진할수록 고령화율이 높습니다. "
    "지도 위에 마우스를 올리면 지역명과 고령화율을 확인할 수 있습니다."
)

st.caption(
    "자료: 제공된 인구 CSV 및 시군구 GeoJSON · "
    "지도 타일 없이 경계 데이터만 사용"
)

with st.spinner("인구 자료와 시군구 경계를 불러오는 중입니다..."):
