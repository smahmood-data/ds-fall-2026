from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


REQUIRED_COLUMNS = {
    "movie_id",
    "rating",
    "title",
    "year",
    "genres",
}


@st.cache_data
def load_and_prepare_data():
    """Load the rating-level file and create reusable analysis tables."""
    data_path = Path(__file__).parent / "data" / "movie_ratings.csv"
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset not found at {data_path}")

    ratings = pd.read_csv(data_path)
    missing_columns = REQUIRED_COLUMNS.difference(ratings.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Dataset is missing required columns: {missing}")

    ratings["rating"] = pd.to_numeric(ratings["rating"], errors="coerce")
    ratings["year"] = pd.to_numeric(ratings["year"], errors="coerce")
    ratings["movie_id"] = pd.to_numeric(ratings["movie_id"], errors="coerce")
    ratings = ratings.dropna(subset=["movie_id", "title", "rating"]).copy()
    ratings["movie_id"] = ratings["movie_id"].astype("int64")

    invalid_ratings = ~ratings["rating"].between(0, 5)
    if invalid_ratings.any():
        ratings = ratings.loc[~invalid_ratings].copy()

    ratings["genres"] = ratings["genres"].fillna("Unknown").replace("", "Unknown")

    movies = (
        ratings[["movie_id", "title", "year", "genres"]]
        .drop_duplicates(subset=["movie_id"])
        .copy()
    )
    movie_genres = movies.assign(genre=movies["genres"].str.split("|"))
    movie_genres = movie_genres.explode("genre")
    movie_genres["genre"] = movie_genres["genre"].str.strip()
    movie_genres = movie_genres[movie_genres["genre"].ne("")].copy()
    movie_genres = movie_genres.drop_duplicates(subset=["movie_id", "genre"])

    rating_genres = ratings[["movie_id", "rating", "title", "year"]].merge(
        movie_genres[["movie_id", "genre"]], on="movie_id", how="inner"
    )
    return ratings, movies, movie_genres, rating_genres


def filter_tables(ratings, movies, movie_genres, rating_genres, selected_genres):
    """Apply the genre filter at movie level, then return consistent tables."""
    if not selected_genres:
        return ratings, movies, movie_genres, rating_genres

    selected_movie_ids = set(
        movie_genres.loc[movie_genres["genre"].isin(selected_genres), "movie_id"]
    )
    filtered_ratings = ratings[ratings["movie_id"].isin(selected_movie_ids)].copy()
    filtered_movies = movies[movies["movie_id"].isin(selected_movie_ids)].copy()
    filtered_movie_genres = movie_genres[
        movie_genres["movie_id"].isin(selected_movie_ids)
    ].copy()
    filtered_rating_genres = rating_genres[
        rating_genres["movie_id"].isin(selected_movie_ids)
    ].copy()
    return (
        filtered_ratings,
        filtered_movies,
        filtered_movie_genres,
        filtered_rating_genres,
    )


def genre_breakdown(movie_genres):
    return (
        movie_genres.groupby("genre", as_index=False)["movie_id"]
        .nunique()
        .rename(columns={"movie_id": "movie_count"})
        .sort_values(["movie_count", "genre"], ascending=[False, True])
    )


def genre_satisfaction(rating_genres):
    return (
        rating_genres.groupby("genre", as_index=False)
        .agg(
            mean_rating=("rating", "mean"),
            rating_count=("rating", "size"),
            movie_count=("movie_id", "nunique"),
        )
        .sort_values(["mean_rating", "rating_count", "genre"], ascending=[False, False, True])
    )


def ratings_by_release_year(ratings):
    return (
        ratings.dropna(subset=["year"])
        .assign(release_year=lambda frame: frame["year"].astype(int))
        .groupby("release_year", as_index=False)
        .agg(
            mean_rating=("rating", "mean"),
            rating_count=("rating", "size"),
            movie_count=("movie_id", "nunique"),
        )
        .sort_values("release_year")
    )


def top_movies(ratings, minimum_ratings):
    return (
        ratings.groupby(["movie_id", "title"], as_index=False)
        .agg(mean_rating=("rating", "mean"), rating_count=("rating", "size"))
        .query("rating_count >= @minimum_ratings")
        .sort_values(
            ["mean_rating", "rating_count", "title"],
            ascending=[False, False, True],
        )
        .head(5)
        .assign(mean_rating=lambda frame: frame["mean_rating"].round(2))
    )


def render_empty_state(message):
    st.info(message)


def rating_axis_range(values):
    """Return a readable, padded range while keeping the rating scale bounded."""
    numeric_values = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if numeric_values.empty:
        return [0, 5]

    minimum = float(numeric_values.min())
    maximum = float(numeric_values.max())
    span = maximum - minimum
    padding = max(span * 0.20, 0.05)
    lower = max(0.0, minimum - padding)
    upper = min(5.0, maximum + padding)

    # Keep a small visible range when all displayed values are identical.
    if upper - lower < 0.10:
        midpoint = (minimum + maximum) / 2
        lower = max(0.0, midpoint - 0.05)
        upper = min(5.0, midpoint + 0.05)

    return [lower, upper]


def main():
    st.set_page_config(
        page_title="MovieLens Dashboard",
        page_icon="🎬",
        layout="wide",
    )

    st.title("🎬 MovieLens Ratings Dashboard")
    st.caption(
        "Explore genre coverage, rating patterns by release year, and highly rated movies."
    )

    try:
        ratings, movies, movie_genres, rating_genres = load_and_prepare_data()
    except (FileNotFoundError, ValueError) as error:
        st.error(str(error))
        st.stop()

    all_genres = sorted(movie_genres["genre"].dropna().unique())
    st.subheader("Interactive controls")
    control_columns = st.columns([2, 1])
    with control_columns[0]:
        selected_genres = st.multiselect(
            "Filter to genres",
            options=all_genres,
            help="Movies matching at least one selected genre are included in every analysis.",
        )
    with control_columns[1]:
        selected_floor = st.slider(
            "Interactive minimum ratings floor",
            min_value=1,
            max_value=250,
            value=50,
            step=1,
            help="Controls the interactive top-movies result. Required comparisons at 50 and 150 remain visible.",
        )

    ratings, movies, movie_genres, rating_genres = filter_tables(
        ratings, movies, movie_genres, rating_genres, selected_genres
    )
    filter_description = (
        "all rated movies"
        if not selected_genres
        else "movies matching: " + ", ".join(selected_genres)
    )
    chart_title_suffix = f" {filter_description}"

    st.subheader("Filtered dataset")
    metric_columns = st.columns(4)
    metric_columns[0].metric("Ratings", f"{len(ratings):,}")
    metric_columns[1].metric("Movies", f"{ratings['movie_id'].nunique():,}")
    metric_columns[2].metric("Genres", f"{movie_genres['genre'].nunique():,}")
    metric_columns[3].metric("Mean rating", f"{ratings['rating'].mean():.2f}")

    if selected_genres:
        st.caption(
            "Genre filtering is applied at the movie level: a movie matching at least one selected genre is included."
        )

    st.subheader("1. Genre breakdown")
    breakdown = genre_breakdown(movie_genres)
    if breakdown.empty:
        render_empty_state("No movies match the selected genres.")
    else:
        figure = px.bar(
            breakdown.sort_values("movie_count"),
            x="movie_count",
            y="genre",
            orientation="h",
            labels={"movie_count": "Distinct rated movies", "genre": "Genre"},
            title="Genre Distribution Among" + chart_title_suffix,
            hover_data={"movie_count": ":,"},
        )
        figure.update_layout(showlegend=False)
        st.plotly_chart(figure, use_container_width=True, key="genre_breakdown_chart")
        st.caption("Movies with multiple genres are counted once in each applicable genre.")

    st.subheader("2. Genre satisfaction")
    satisfaction = genre_satisfaction(rating_genres)
    if satisfaction.empty:
        render_empty_state("No genre ratings are available for the selected filter.")
    else:
        figure = px.bar(
            satisfaction.sort_values("mean_rating"),
            x="mean_rating",
            y="genre",
            orientation="h",
            labels={"mean_rating": "Mean rating", "genre": "Genre"},
            title="Average Rating by Genre Among" + chart_title_suffix,
            hover_data={
                "mean_rating": ":.2f",
                "rating_count": ":,",
                "movie_count": ":,",
            },
        )
        figure.update_xaxes(range=rating_axis_range(satisfaction["mean_rating"]))
        figure.update_layout(showlegend=False)
        st.plotly_chart(figure, use_container_width=True, key="genre_satisfaction_chart")
        st.caption("A rating contributes to every genre assigned to its movie.")

    st.subheader("3. Mean rating by movie release year")
    yearly = ratings_by_release_year(ratings)
    if yearly.empty:
        render_empty_state("No valid movie release years are available for the selected filter.")
    else:
        figure = px.line(
            yearly,
            x="release_year",
            y="mean_rating",
            markers=True,
            labels={"release_year": "Movie release year", "mean_rating": "Mean rating"},
            title="Mean Rating Across Release Years Among" + chart_title_suffix,
            hover_data={"mean_rating": ":.2f", "rating_count": ":,", "movie_count": ":,"},
        )
        figure.update_yaxes(range=rating_axis_range(yearly["mean_rating"]))
        st.plotly_chart(figure, use_container_width=True, key="release_year_chart")
        st.caption("This chart uses movie release year, not the year when the rating was submitted.")

    st.subheader("4. Best movies with a rating floor")
    comparison_columns = st.columns(2)
    for column, floor in zip(comparison_columns, (50, 150)):
        with column:
            result = top_movies(ratings, floor)
            st.markdown(
                f"**Top 5 movies with at least {floor} ratings | {filter_description}**"
            )
            if result.empty:
                render_empty_state(f"No movies have at least {floor} ratings in this filter.")
            else:
                figure = px.bar(
                    result.sort_values("mean_rating", ascending=False),
                    x="title",
                    y="mean_rating",
                    labels={"mean_rating": "Mean rating", "title": "Movie"},
                    hover_data={"mean_rating": ":.2f", "rating_count": ":,"},
                )
                figure.update_xaxes(tickangle=-35)
                figure.update_yaxes(range=rating_axis_range(result["mean_rating"]))
                figure.update_layout(showlegend=False)
                st.plotly_chart(
                    figure,
                    use_container_width=True,
                    key=f"top_movies_{floor}_chart",
                )

    interactive_result = top_movies(ratings, selected_floor)
    st.subheader(
        f"Interactive top 5 with at least {selected_floor} ratings | {filter_description}"
    )
    if interactive_result.empty:
        render_empty_state(f"No movies have at least {selected_floor} ratings in this filter.")
    else:
        figure = px.bar(
            interactive_result.sort_values("mean_rating", ascending=False),
            x="title",
            y="mean_rating",
            labels={"mean_rating": "Mean rating", "title": "Movie"},
            hover_data={"mean_rating": ":.2f", "rating_count": ":,"},
        )
        figure.update_xaxes(tickangle=-35)
        figure.update_yaxes(range=rating_axis_range(interactive_result["mean_rating"]))
        figure.update_layout(showlegend=False)
        st.plotly_chart(
            figure,
            use_container_width=True,
            key="interactive_top_movies_chart",
        )
        st.caption("Hover over a bar to see the number of ratings for each movie.")


if __name__ == "__main__":
    main()
