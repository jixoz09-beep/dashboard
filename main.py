import re

import pandas as pd
import plotly.graph_objects as go
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

st.set_page_config(
    page_title="전국 고령화·유소년 비율 단계구분도",
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
# 2. 지역 코드 처리
# ==========================================

def normalize_code(value) -> str:
    """코드를 문자열로 정리한다."""

    if value is None or pd.isna(value):
        return ""

    code = str(value).strip()

    if code.endswith(".0"):
        code = code[:-2]

    return code


def canonicalize_sgg_code(value) -> str:
    """시군구 5자리 코드를 현행 경계 코드로 보정한다."""

    code = normalize_code(value)

    if not code:
        return ""

    if code.isdigit() and len(code) < 5:
        code = code.zfill(5)

    if len(code) > 5:
        code = code[:5]

    # 행정구역 개편 코드 보정
    if code == "47720":
        code = "27720"  # 군위군
    elif code.startswith("42"):
        code = "51" + code[2:]  # 옛 강원도 코드
    elif code.startswith("45"):
        code = "52" + code[2:]  # 옛 전라북도 코드

    return code


def sgg_code_from_dong(value) -> str:
    """읍·면·동 코드 앞 5자리에서 시군구 코드를 만든다."""

    code = normalize_code(value)

    if not code:
        return ""

    if code.isdigit() and len(code) < 5:
        code = code.zfill(5)

    return canonicalize_sgg_code(code[:5])


# ==========================================
# 3. 인구 데이터 읽기
# ==========================================

@st.cache_data(ttl=21600, show_spinner=False)
def load_population_data():
    """ZIP CSV를 읽고 연도·나이별 열을 준비한다."""

    df = pd.read_csv(
        POPULATION_URL,
        compression="zip",
        dtype={"코드": "string"},
        low_memory=False,
    )

    df.columns = [str(col).strip() for col in df.columns]

    required = {"연도", "코드"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            "인구 자료에 필요한 열이 없습니다: "
            + ", ".join(sorted(missing))
        )

    # 연도값이 숫자 또는 '2026년' 형태여도 연도를 추출한다.
    year_text = df["연도"].astype("string").str.extract(
        r"(\d{4})", expand=False
    )

    df["_연도"] = pd.to_numeric(year_text, errors="coerce")

    # 전체 인구는 '계_'로 시작하는 열만 합산한다.
    total_cols = [
        col for col in df.columns if col.startswith("계_")
    ]

    if not total_cols:
        raise ValueError(
            "'계_'로 시작하는 인구 열을 찾지 못했습니다."
        )

    # 열 이름에서 나이를 추출한다.
    # '계_100세 이상'도 정상적으로 인식한다.
    age_by_col = {}

    for col in total_cols:
        match = re.fullmatch(
            r"계_(\d+)세(?:\s*이상)?",
            col.strip(),
        )

        if match:
            age_by_col[col] = int(match.group(1))

    senior_cols = [
        col
        for col, age in age_by_col.items()
        if age >= 65
    ]

    child_cols = [
        col
        for col, age in age_by_col.items()
        if 0 <= age <= 14
    ]

    if not senior_cols:
        raise ValueError(
            "'계_65세'부터 '계_100세 이상'까지의 "
            "열을 찾지 못했습니다."
        )

    if not child_cols:
        raise ValueError(
            "'계_0세'부터 '계_14세'까지의 "
            "열을 찾지 못했습니다."
        )

    # 인구 열을 숫자로 변환한다.
    for col in total_cols:
        df[col] = pd.to_numeric(
            df[col]
            .astype("string")
            .str.replace(",", "", regex=False),
            errors="coerce",
        ).fillna(0)

    # 동 코드 앞 5자리로 시군구 코드를 만들고 개편 코드를 보정한다.
    df["_시군구코드"] = (
        df["코드"]
        .map(sgg_code_from_dong)
        .astype("string")
    )

    years = sorted(
        int(year)
        for year in df["_연도"].dropna().unique()
    )

    if not years:
        raise ValueError(
            "인구 자료에서 유효한 연도를 찾지 못했습니다."
        )

    return df, total_cols, senior_cols, child_cols, years


# ==========================================
# 4. 시군구 경계 GeoJSON 읽기
# ==========================================

@st.cache_data(ttl=21600, show_spinner=False)
def load_geojson():
    """requests로 GeoJSON을 받고 코드를 문자열로 정리한다."""

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

        properties["코드"] = canonicalize_sgg_code(
            properties.get("코드")
        )

    return geojson


def geo_metadata(geojson) -> pd.DataFrame:
    """GeoJSON에서 코드·시군구·시도 정보를 만든다."""

    rows = []

    for feature in geojson["features"]:
        properties = feature.get("properties", {})

        code = canonicalize_sgg_code(
            properties.get("코드")
        )

        if not code:
            continue

        rows.append(
            {
                "코드": code,
                "시군구": str(
                    properties.get("시군구", "이름 없음")
                ),
                "시도": str(
                    properties.get("시도", "")
                ),
            }
        )

    meta = pd.DataFrame(rows)

    if meta.empty:
        raise ValueError(
            "GeoJSON에서 시군구 코드 정보를 찾지 못했습니다."
        )

    return meta.drop_duplicates(subset=["코드"])


# ==========================================
# 5. 연도·지표별 시군구 통계
# ==========================================

def calculate_sgg_rates(
    df: pd.DataFrame,
    total_cols: list,
    numerator_cols: list,
    selected_year: int,
):
    """선택 연도의 시군구 비율과 전국 비율을 계산한다."""

    year_df = df.loc[
        df["_연도"].eq(selected_year)
    ].copy()

    if year_df.empty:
        raise ValueError(
            f"{selected_year}년 인구 자료가 없습니다."
        )

    # 전체 인구와 선택 지표의 인구를 계산한다.
    year_df["_전체인구"] = year_df[total_cols].sum(axis=1)

    year_df["_지표인구"] = year_df[numerator_cols].sum(axis=1)

    # 전국 비율은 전체 인구를 기준으로 계산한다.
    national_total = float(
        year_df["_전체인구"].sum()
    )

    national_numerator = float(
        year_df["_지표인구"].sum()
    )

    national_rate = (
        national_numerator / national_total * 100
        if national_total > 0
        else None
    )

    # 유효한 시군구 코드만 묶는다.
    usable = year_df.loc[
        year_df["_시군구코드"].notna()
        & year_df["_시군구코드"].ne("")
    ].copy()

    stats = (
        usable.groupby("_시군구코드", as_index=False)
        .agg(
            **{
                "지표 인구": ("_지표인구", "sum"),
                "전체 인구": ("_전체인구", "sum"),
            }
        )
    )

    denominator = stats["전체 인구"].where(
        stats["전체 인구"] > 0
    )

    stats["지표 비율(%)"] = (
        stats["지표 인구"]
        .div(denominator)
        .mul(100)
    )

    return stats, national_rate


def build_map_data(geojson, stats) -> pd.DataFrame:
    """경계 데이터와 인구 통계를 코드 기준으로 결합한다."""

    meta = geo_metadata(geojson)

    # 지역 이름이 아닌 코드로 결합한다.
    map_df = meta.merge(
        stats,
        left_on="코드",
        right_on="_시군구코드",
        how="left",
    )

    return map_df


# ==========================================
# 6. 앱 제목 및 자료 로딩
# ==========================================

st.title("🗺️ 전국 고령화·유소년 비율 단계구분도")

st.write(
    "연도와 지표를 선택해 시군구별 인구 비율을 비교해 보세요. "
    "색 구간은 연도가 바뀌어도 고정되어 있어 "
    "연도별 차이를 비교할 수 있습니다."
)

st.caption(
    "인구 자료: 제공된 연도별 인구 ZIP CSV · "
    "경계 자료: 제공된 시군구 GeoJSON"
)

with st.spinner(
    "인구 자료와 시군구 경계를 불러오는 중입니다..."
):
    try:
        (
            population_df,
            total_cols,
            senior_cols,
            child_cols,
            available_years,
        ) = load_population_data()

        geojson_data = load_geojson()

        metadata_df = geo_metadata(geojson_data)

    except Exception as exc:
        st.error(
            "데이터를 불러오거나 처리하지 못했습니다. "
            "인터넷 연결과 원본 파일 주소를 확인해 주세요."
        )

        with st.expander("오류 상세 보기"):
            st.exception(exc)

        st.stop()


# ==========================================
# 7. 연도·지표·시도 선택
# ==========================================

control_year, control_metric, control_sido = st.columns(
    [2, 1, 1]
)

selected_year = control_year.slider(
    "연도",
    min_value=int(min(available_years)),
    max_value=int(max(available_years)),
    value=int(max(available_years)),
    step=1,
)

metric_choice = control_metric.selectbox(
    "지표 선택",
    [
        "65세 이상 비율 (고령화율)",
        "0~14세 비율 (유소년)",
    ],
)

sido_values = sorted(
    value.strip()
    for value in metadata_df["시도"].dropna().astype(str).unique()
    if value.strip()
)

sido_options = ["전국"] + sido_values

selected_sido = control_sido.selectbox(
    "시도 선택",
    sido_options,
    index=0,
)


# ==========================================
# 8. 지표별 고정 색 구간 설정
# ==========================================

if metric_choice == "65세 이상 비율 (고령화율)":

    numerator_cols = senior_cols

    rate_label = "고령화율"

    national_metric_label = "전국 고령화율"

    # 고령화율 구간은 모든 연도에서 고정한다.
    thresholds = [19, 23, 28, 38]

    band_labels = [
        "<19%",
        "19–23%",
        "23–28%",
        "28–38%",
        "≥38%",
    ]

    metric_table_label = "고령화율(%)"

else:

    numerator_cols = child_cols

    rate_label = "유소년 비율"

    national_metric_label = "전국 유소년 비율"

    # 유소년 비율에 맞는 별도 구간을 사용한다.
    thresholds = [6, 9, 12, 15]

    band_labels = [
        "<6%",
        "6–9%",
        "9–12%",
        "12–15%",
        "≥15%",
    ]

metric_table_label = (
    "고령화율(%)"
    if rate_label == "고령화율"
    else "유소년 비율(%)"
)

# 낮은 비율부터 높은 비율 순서로 색상을 고정한다.
band_colors = {
    band_labels[0]: "#fff7bc",
    band_labels[1]: "#fee391",
    band_labels[2]: "#fec44f",
    band_labels[3]: "#fe9929",
    band_labels[4]: "#8c2d04",
}


# ==========================================
# 9. 선택 연도·지표 계산
# ==========================================

try:
    stats, national_rate = calculate_sgg_rates(
        population_df,
        total_cols,
        numerator_cols,
        selected_year,
    )

    map_data = build_map_data(
        geojson_data,
        stats,
    )

except Exception as exc:
    st.error(
        "선택한 연도의 통계를 계산하지 못했습니다."
    )

    with st.expander("오류 상세 보기"):
        st.exception(exc)

    st.stop()


# ==========================================
# 10. 시도별 지도 범위 선택
# ==========================================

if selected_sido == "전국":

    view_data = map_data.copy()

    view_features = list(
        geojson_data["features"]
    )

else:

    view_data = map_data.loc[
        map_data["시도"].eq(selected_sido)
    ].copy()

    view_features = [
        feature
        for feature in geojson_data["features"]
        if str(
            feature.get("properties", {}).get("시도", "")
        ).strip() == selected_sido
    ]


# 선택된 지역만 GeoJSON으로 구성하여 지도 확대에 사용한다.
view_geojson = {
    key: value
    for key, value in geojson_data.items()
    if key != "features"
}

view_geojson["features"] = view_features

# 공통 지표 비율 열
view_data["_비율"] = pd.to_numeric(
    view_data["지표 비율(%)"],
    errors="coerce",
)

matched_data = view_data.loc[
    view_data["_비율"].notna()
].copy()

unmatched_data = view_data.loc[
    view_data["_비율"].isna()
].copy()


# ==========================================
# 11. 고정 구간에 따라 색상 분류
# ==========================================

if not matched_data.empty:

    matched_data["색 구간"] = pd.cut(
        matched_data["_비율"],
        bins=[
            float("-inf"),
            *thresholds,
            float("inf"),
        ],
        labels=band_labels,
        right=False,
        ordered=True,
    ).astype(str)


# ==========================================
# 12. 지표 카드 3장
# ==========================================

metric1, metric2, metric3 = st.columns(3)

national_display = (
    f"{national_rate:.2f}%"
    if national_rate is not None
    else "계산 불가"
)

metric1.metric(
    national_metric_label,
    national_display,
)

if not matched_data.empty:

    highest = matched_data.loc[
        matched_data["_비율"].idxmax()
    ]

    lowest = matched_data.loc[
        matched_data["_비율"].idxmin()
    ]

    metric2.metric(
        "가장 높은 시군구",
        str(highest["시군구"]),
        f"{highest['_비율']:.2f}%",
    )

    metric3.metric(
        "가장 낮은 시군구",
        str(lowest["시군구"]),
        f"{lowest['_비율']:.2f}%",
    )

else:

    metric2.metric(
        "가장 높은 시군구",
        "자료 없음",
    )

    metric3.metric(
        "가장 낮은 시군구",
        "자료 없음",
    )

st.caption(
    f"지도 범위: {selected_sido} · "
    "시군구 최고·최저는 현재 지도에 표시된 지역 중에서 계산합니다."
)


# ==========================================
# 13. Plotly 단계구분도
# ==========================================

fig = go.Figure()


# ------------------------------------------
# 13-1. 자료가 연결되지 않은 지역은 회색으로 표시
# ------------------------------------------

if not unmatched_data.empty:

    fig.add_trace(
        go.Choropleth(
            geojson=view_geojson,

            locations=(
                unmatched_data["코드"]
                .astype(str)
                .tolist()
            ),

            featureidkey="properties.코드",

            z=[0] * len(unmatched_data),

            zmin=0,
            zmax=1,

            colorscale=[
                [0, "#c7c7c7"],
                [1, "#c7c7c7"],
            ],

            showscale=False,

            name="자료 없음 / 코드 불일치",
            showlegend=True,

            marker_line_color="#fffaf0",
            marker_line_width=0.7,

            customdata=unmatched_data[
                ["시군구", "시도", "코드"]
            ].to_numpy(),

            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "%{customdata[1]}<br>"
                "자료 없음 또는 코드 불일치"
                "<extra></extra>"
            ),
        )
    )


# ------------------------------------------
# 13-2. 각 색 구간을 고정 색상으로 표시
# ------------------------------------------

for band in band_labels:

    subset = matched_data.loc[
        matched_data["색 구간"].eq(band)
    ].copy()

    color = band_colors[band]

    fig.add_trace(
        go.Choropleth(
            geojson=view_geojson,

            locations=(
                subset["코드"]
                .astype(str)
                .tolist()
            ),

            featureidkey="properties.코드",

            # 각 구간에 단일 색상을 지정한다.
            z=[0] * len(subset),

            zmin=0,
            zmax=1,

            colorscale=[
                [0, color],
                [1, color],
            ],

            showscale=False,

            name=band,
            showlegend=True,

            marker_line_color="#fffaf0",
            marker_line_width=0.7,

            customdata=subset[
                ["시군구", "_비율"]
            ].to_numpy(),

            hovertemplate=(
                f"<b>%{{customdata[0]}}</b><br>"
                f"{rate_label}: %{{customdata[1]:.2f}}%"
                "<extra></extra>"
            ),
        )
    )


# ------------------------------------------
# 13-3. 지도 디자인 및 확대
# ------------------------------------------

fig.update_geos(
    fitbounds="locations",
    visible=False,
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
        "t": 15,
        "b": 20,
    },

    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",

    legend={
        "title": {
            "text": f"{rate_label} 구간",
        },
        "orientation": "h",
        "yanchor": "bottom",
        "y": -0.02,
        "xanchor": "left",
        "x": 0,
        "font": {
            "size": 12,
        },
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
# 14. 지도 아래 코드 불일치 안내
# ==========================================

if not unmatched_data.empty:

    st.warning(
        f"회색으로 표시된 지역 {len(unmatched_data):,}곳은 "
        f"{selected_year}년 인구 자료와 경계 코드가 연결되지 않아 "
        "비율을 계산하지 못한 곳입니다. "
        "옛 시도 코드 42→51, 45→52와 군위군 코드 "
        "47720→27720은 보정했습니다. "
        "그래도 일치하지 않는 지역은 회색으로 남겨 두었습니다. "
        "자료에 해당 지역이 없거나 추가적인 행정구역 코드 변경이 "
        "원인일 수 있습니다."
    )

else:

    st.caption(
        "회색은 선택 연도 인구 자료와 코드가 연결되지 않은 지역을 뜻합니다. "
        "현재 지도 범위에서는 연결되지 않은 지역이 없습니다."
    )


# ==========================================
# 15. 시군구별 상세 통계표
# ==========================================

with st.expander("📊 시군구별 비율 표 보기"):

    if matched_data.empty:

        st.info(
            "선택한 지역에 표시할 인구 통계가 없습니다."
        )

    else:

        table = matched_data[
            [
                "시도",
                "시군구",
                "코드",
                "지표 인구",
                "전체 인구",
                "_비율",
            ]
        ].copy()

        table = table.sort_values(
            "_비율",
            ascending=False,
        )

        table = table.rename(
            columns={
                "_비율": metric_table_label,
            }
        )

        table["지표 인구"] = (
            table["지표 인구"]
            .round()
            .astype("int64")
        )

        table["전체 인구"] = (
            table["전체 인구"]
            .round()
            .astype("int64")
        )

        table[metric_table_label] = (
            table[metric_table_label]
            .round(2)
        )

        st.dataframe(
            table,
            use_container_width=True,
            hide_index=True,
        )
