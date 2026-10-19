import re

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# ==========================================
# 1. 데이터 주소 및 기본 설정
# ==========================================

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
        background-color: #fffaf0;
    }

    h1, h2, h3 {
        color: #573d2b;
    }

    div[data-testid="stMetric"] {
        background-color: #fff3d6;
        border: 1px solid #f1dfb9;
        border-radius: 12px;
        padding: 12px 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ==========================================
# 2. 지역 코드 문자열 정리
# ==========================================

def normalize_code(value) -> str:
    """지역 코드를 문자열로 통일하고 필요한 경우 앞에 0을 채운다."""

    if value is None or pd.isna(value):
        return ""

    code = str(value).strip()

    # 숫자가 실수 형태로 읽힌 경우 처리
    if code.endswith(".0"):
        code = code[:-2]

    # 숫자형 코드의 앞자리 0이 사라진 경우 보정
    if code.isdigit() and len(code) < 5:
        code = code.zfill(5)

    return code


# ==========================================
# 3. 인구 데이터 불러오기 및 계산
# ==========================================

@st.cache_data(ttl=21600, show_spinner=False)
def load_population() -> pd.DataFrame:
    """2026년 인구 자료를 읽어 시군구별 고령화율을 계산한다."""

    df = pd.read_csv(
        POPULATION_URL,
        compression="zip",
        dtype={"코드": "string"},
        low_memory=False,
    )

    # 열 이름의 앞뒤 공백 제거
    df.columns = [str(col).strip() for col in df.columns]

    # 필수 열 확인
    required_columns = {"연도", "코드"}
    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(
            "필수 열이 없습니다: "
            + ", ".join(sorted(missing_columns))
        )

    # 2026년 데이터만 선택
    year_values = (
        df["연도"]
        .astype("string")
        .str.extract(r"(\d{4})", expand=False)
    )

    df = df.loc[year_values.eq(TARGET_YEAR)].copy()

    if df.empty:
        raise ValueError(
            "인구 데이터에서 2026년 자료를 찾지 못했습니다."
        )

    # '계_'로 시작하는 열만 전체 인구 계산에 사용
    # 남_ 및 여_ 열은 더하지 않는다.
    total_columns = [
        col
        for col in df.columns
        if col.startswith("계_")
    ]

    if not total_columns:
        raise ValueError(
            "'계_'로 시작하는 인구 열이 없습니다."
        )

    # 65세 이상 인구에 해당하는 열 찾기
    # 예: 계_65세, 계_66세, ..., 계_100세 이상
    senior_columns = []

    for col in total_columns:
        match = re.fullmatch(
            r"계_(\d+)세(?:\s*이상)?",
            col.strip(),
        )

        if match and int(match.group(1)) >= 65:
            senior_columns.append(col)

    if not senior_columns:
        raise ValueError(
            "65세 이상 인구 열을 찾지 못했습니다. "
            "원본 데이터의 열 이름을 확인해 주세요."
        )

    # 인구 데이터를 숫자로 변환
    # 혹시 쉼표가 들어간 숫자 문자열이 있어도 처리
    for col in total_columns:
        df[col] = pd.to_numeric(
            df[col]
            .astype("string")
            .str.replace(",", "", regex=False),
            errors="coerce",
        ).fillna(0)

    # 읍·면·동별 전체 인구
    df["전체 인구"] = df[total_columns].sum(axis=1)

    # 읍·면·동별 65세 이상 인구
    df["65세 이상 인구"] = df[senior_columns].sum(axis=1)

    # 동 코드의 앞 5자리를 시군구 코드로 사용
    df["동코드"] = df["코드"].map(normalize_code)

    df["시군구코드"] = (
        df["동코드"]
        .astype("string")
        .str[:5]
    )

    df = df.loc[
        df["시군구코드"].notna()
        & df["시군구코드"].ne("")
    ].copy()

    # 시군구별 인구 합산
    grouped = (
        df.groupby("시군구코드", as_index=False)[
            ["65세 이상 인구", "전체 인구"]
        ]
        .sum()
    )

    # 고령화율 = 65세 이상 인구 / 전체 인구 × 100
    denominator = grouped["전체 인구"].where(
        grouped["전체 인구"] > 0
    )

    grouped["고령화율(%)"] = (
        grouped["65세 이상 인구"]
        .div(denominator)
        .mul(100)
    )

    return grouped


# ==========================================
# 4. 시군구 경계 GeoJSON 불러오기
# ==========================================

@st.cache_data(ttl=21600, show_spinner=False)
def load_geojson() -> dict:
    """시군구 경계 GeoJSON을 내려받고 코드 형식을 통일한다."""

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
        raise ValueError(
            "시군구 GeoJSON 형식이 올바르지 않습니다."
        )

    for feature in geojson["features"]:
        properties = feature.setdefault("properties", {})

        # 경계 코드도 문자열로 통일
        properties["코드"] = normalize_code(
            properties.get("코드")
        )

    return geojson


# ==========================================
# 5. 코드로 인구 자료와 경계 자료 결합
# ==========================================

def build_map_data(
    geojson: dict,
    population_stats: pd.DataFrame,
) -> pd.DataFrame:
    """지역명이 아니라 시군구 코드로 두 자료를 결합한다."""

    geo_rows = []

    for feature in geojson["features"]:
        properties = feature.get("properties", {})

        code = normalize_code(properties.get("코드"))

        # 코드가 없는 경계는 제외
        if not code:
            continue

        geo_rows.append(
            {
                "코드": code,
                "시군구": properties.get("시군구", "이름 없음"),
                "시도": properties.get("시도", ""),
            }
        )

    geo_df = pd.DataFrame(geo_rows)

    if geo_df.empty:
        raise ValueError(
            "GeoJSON에서 시군구 코드를 찾지 못했습니다."
        )

    # 경계 코드 중복 제거
    geo_df = geo_df.drop_duplicates(
        subset=["코드"]
    )

    stats = population_stats.copy()

    stats["시군구코드"] = (
        stats["시군구코드"]
        .map(normalize_code)
    )

    # 반드시 코드로 결합
    map_df = geo_df.merge(
        stats,
        left_on="코드",
        right_on="시군구코드",
        how="left",
    )

    return map_df


# ==========================================
# 6. 앱 화면
# ==========================================

st.title("🗺️ 전국 고령화 단계구분도")

st.write(
    "2026년 인구 데이터를 이용해 전국 시군구별 "
    "65세 이상 인구 비율을 지도에 표시합니다. "
    "색이 진할수록 고령화율이 높습니다."
)

st.caption(
    "인구 데이터: 제공된 연도별 인구 ZIP CSV | "
    "경계 데이터: 제공된 시군구 GeoJSON"
)


# ==========================================
# 7. 데이터 불러오기
# ==========================================

with st.spinner("인구 자료와 시군구 경계를 불러오는 중입니다..."):
    try:
        population_stats = load_population()

        geojson_data = load_geojson()

        map_data = build_map_data(
            geojson_data,
            population_stats,
        )

    except Exception as exc:
        st.error(
            "데이터를 불러오거나 처리하지 못했습니다. "
            "인터넷 연결과 원본 파일 주소를 확인해 주세요."
        )

        with st.expander("오류 상세 보기"):
            st.exception(exc)

        st.stop()


# ==========================================
# 8. 연결된 시군구 확인
# ==========================================

matched = map_data["고령화율(%)"].notna()

plot_data = map_data.loc[matched].copy()

matched_count = len(plot_data)

geo_count = map_data["코드"].nunique()

if plot_data.empty:
    st.error(
        "인구 데이터와 GeoJSON 경계의 코드가 일치하지 않습니다. "
        "두 파일의 코드 형식을 확인해 주세요."
    )
    st.stop()


# ==========================================
# 9. 상단 지표 카드
# ==========================================

metric1, metric2, metric3 = st.columns(3)

metric1.metric(
    "표시된 시군구",
    f"{matched_count:,}곳",
)

average_rate = plot_data["고령화율(%)"].mean()

metric2.metric(
    "표시 지역의 평균 고령화율",
    f"{average_rate:.2f}%",
)

max_row = plot_data.loc[
    plot_data["고령화율(%)"].idxmax()
]

metric3.metric(
    "고령화율 최고 지역",
    str(max_row["시군구"]),
    f"{max_row['고령화율(%)']:.2f}%",
)


# ==========================================
# 10. Plotly 단계구분도
# ==========================================

fig = px.choropleth(
    plot_data,
    geojson=geojson_data,
    locations="코드",
    featureidkey="properties.코드",
    color="고령화율(%)",
    color_continuous_scale=[
        [0.00, "#fff7bc"],
        [0.20, "#fee391"],
        [0.40, "#fec44f"],
        [0.60, "#fe9929"],
        [0.80, "#d95f0e"],
        [1.00, "#8c2d04"],
    ],
    hover_name="시군구",
    hover_data={
        "코드": False,
        "시군구코드": False,
        "시도": False,
        "65세 이상 인구": False,
        "전체 인구": False,
        "고령화율(%)": False,
    },
    labels={
        "고령화율(%)": "고령화율",
    },
)

# 마우스를 올렸을 때 시군구 이름과 고령화율 표시
fig.update_traces(
    marker_line_color="#fffaf0",
    marker_line_width=0.7,
    customdata=plot_data[["시군구"]].to_numpy(),
    hovertemplate=(
        "<b>%{customdata[0]}</b><br>"
        "고령화율: %{z:.2f}%"
        "<extra></extra>"
    ),
)

# 배경 타일 없이 GeoJSON 경계만 표시
fig.update_geos(
    fitbounds="locations",
    projection_type="mercator",
    showframe=False,
    showcoastlines=False,
    showcountries=False,
    showland=False,
    showocean=False,
    showlakes=False,
    showrivers=False,
    bgcolor="rgba(0,0,0,0)",
)

fig.update_layout(
    height=760,
    margin={
        "l": 0,
        "r": 0,
        "t": 20,
        "b": 0,
    },
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    coloraxis_colorbar={
        "title": {
            "text": "고령화율(%)",
        },
        "ticksuffix": "%",
        "thickness": 16,
    },
)

st.plotly_chart(
    fig,
    use_container_width=True,
    config={
        "displayModeBar": False,
        "scrollZoom": True,
    },
)


# ==========================================
# 11. 데이터 연결 상태
# ==========================================

unmatched_count = max(
    geo_count - matched_count,
    0,
)

if unmatched_count > 0:
    st.warning(
        f"전체 경계 {geo_count:,}곳 중 "
        f"{matched_count:,}곳이 인구 자료와 연결되었습니다. "
        f"연결되지 않은 경계는 {unmatched_count:,}곳입니다. "
        "자료의 코드 형식과 지역 범위를 확인해 주세요."
    )


# ==========================================
# 12. 시군구별 상세 통계표
# ==========================================

with st.expander("📊 시군구별 고령화율 표 보기"):
    table = plot_data[
        [
            "시도",
            "시군구",
            "코드",
            "65세 이상 인구",
            "전체 인구",
            "고령화율(%)",
        ]
    ].copy()

    table = table.sort_values(
        "고령화율(%)",
        ascending=False,
    )

    table["65세 이상 인구"] = (
        table["65세 이상 인구"]
        .round()
        .astype("int64")
    )

    table["전체 인구"] = (
        table["전체 인구"]
        .round()
        .astype("int64")
    )

    table["고령화율(%)"] = (
        table["고령화율(%)"]
        .round(2)
    )

    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
    )
