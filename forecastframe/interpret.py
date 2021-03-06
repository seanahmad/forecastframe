import altair as alt
import pandas as pd
import numpy as np
import datetime
import shap


from forecastframe.utilities import (
    _get_processed_outputs,
    _convert_nonnumerics_to_objects,
    _calc_weighted_average,
    _search_list_for_substrings,
)

import forecastframe.model as model


# Set up altair theme
def Lato():
    font = "Arial"

    return {
        "config": {
            "title": {"font": font},
            "axis": {"labelFont": font, "titleFont": font},
            "header": {"labelFont": font, "titleFont": font},
            "legend": {"labelFont": font, "titleFont": font},
        }
    }


alt.themes.register("Lato", Lato)
alt.themes.enable("Lato")


def _format_percentage(percentage):
    return "{:.2%}".format(percentage)


def _get_max_fold(self):
    return max(self.results.keys())


## Errors


def _calc_MAPE(actuals: np.array, predictions: np.array):
    """Calculates the Mean Absolute Percent Error (MAPE) for two arrays."""

    return np.mean(np.abs((actuals - predictions) / actuals))


def _calc_MAPA(actuals: np.array, predictions: np.array, weights=None):
    """Calculates the Mean Absolute Percent Accuracy (MAPA) for two arrays."""
    return 1 - _calc_MAPE(actuals=actuals, predictions=predictions, weights=weights)


def _calc_AE(actuals: np.array, predictions: np.array):
    """Calculates the Absolute Error (AE) for two arrays."""
    return np.abs(actuals - predictions)


def _calc_APA(actuals: np.array, predictions: np.array):
    """Calculates the Absolute Percent Accuracy (APA) for two arrays."""
    return 1 - _calc_APE(actuals=actuals, predictions=predictions)


def _calc_APE(actuals: np.array, predictions: np.array):
    """Calculates the Absolute Percent Error (APE) for two arrays."""
    return np.abs((actuals - predictions) / actuals)


def _calc_SE(actuals: np.array, predictions: np.array):
    """Calculates the squared error (SE) for two arrays."""
    return (actuals - predictions) ** 2


def _calc_MSE(actuals: np.array, predictions: np.array, weights=None):
    """Calculates the Mean Squared Error (MAPE) for two arrays."""
    from sklearn.metrics import mean_squared_error

    return mean_squared_error(
        y_true=actuals,
        y_pred=predictions,
        sample_weight=weights,
        multioutput="raw_values",
    )


def _calc_RMSE(actuals: np.array, predictions: np.array, weights=None):
    """Calculates the Root Mean Squared Error (RMSE) for two arrays."""
    from sklearn.metrics import mean_squared_error

    return np.sqrt(
        mean_squared_error(
            y_true=actuals,
            y_pred=predictions,
            sample_weight=weights,
            multioutput="raw_values",
        )
    )[0]


def _calc_error_metric(
    actuals: np.array, predictions: np.array, error_function=_calc_RMSE, **kwargs
):
    """
    Wrapper function that's meant to be used instead of directly calling _calc_RMSE, _calc_MSE< etc.
    """
    # filter out nulls from the actual and prediction arrays
    null_mask = actuals.isnull()
    actuals = actuals[~null_mask]
    predictions = predictions[~null_mask]

    return error_function(actuals=actuals, predictions=predictions, **kwargs)


def _get_error_func_dict():
    return {
        "Actuals": lambda actuals, predictions: actuals,
        "Predictions": lambda actuals, predictions: predictions,
        "Absolute Percent Error": _calc_APE,
        "Absolute Error": _calc_AE,
        "Squared Error": _calc_SE,
    }


def get_cross_validation_errors(self, describe=True):
    """
    Calculate the in-sample and out-of-sample error metrics for the data found in .cross_validations

    Parameters
    ----------
    describe: bool, default True
        If True, returns a summary of the error metric distribution rather than the actual errors.
    """

    assert (
        self.cross_validations
    ), "Please run .cross_validate before calling this function"

    function_mapping_dict = _get_error_func_dict()

    result_list = []

    for fold in self.cross_validations:
        train, test = fold["train"], fold["test"]
        result_list.append(
            {
                "In-Sample": _calc_errors(self=self, data=train, describe=describe),
                "Out-of-Sample": _calc_errors(self=self, data=test, describe=describe),
            }
        )

    return result_list


def _calc_errors(self, data, describe):
    """
    Calculate all error metrics using the function outlined in _get_error_func_dict
    """

    function_mapping_dict = _get_error_func_dict()

    data = data.copy()

    for metric in function_mapping_dict.keys():
        data.loc[:, metric] = function_mapping_dict[metric](
            actuals=data[self.target],
            predictions=data[f"predicted_{self.target}"],
        ).replace([-np.inf, np.inf], np.nan)

    if describe:
        # filter out rows where we're missing actuals
        data = data[~data[self.target].isnull()]
        data = data.describe()

    return data[function_mapping_dict.keys()]


def _get_data_to_analyze(self):
    if self.cross_validations:
        data = self.cross_validations[-1]["test"]
    elif self.predictions is not None:
        data = self.predictions
    else:
        raise ValueError(
            "Please call .predict or .cross_validate before calculating errors."
        )

    return data


def get_errors(self, data=None, describe=True):
    """
    Calculate in-sample error metrics using the predictions found in .predictions

    Parameters
    ----------
    describe: bool, default True
        If True, returns a summary of the error metric distribution rather than the actual errors.
    data: pd.DataFrame, default None
        If None, uses the last cross_validation set (if it exists), or the last prediction set if it doesn't
    """
    if data is None:
        data = _get_data_to_analyze(self)

    return _calc_errors(self=self, data=data, describe=describe)


## Summaries
def summarize_shap(self):
    """
    Summarize the SHAP values of our LightGBM estimator

    Parameters
    ----------
    """

    sorted_shap_values = self.get_sorted_shap_values()

    sorted_features = sorted_shap_values["feature"].values
    top_features_text = f"{sorted_features[0]}, {sorted_features[1]}, {sorted_features[2]}, and {sorted_features[3]}"

    shap_means = sorted_shap_values["value"].values
    top_4_shap_perc = shap_means[:4].sum() / shap_means.sum()

    bottom_features_text = f"{sorted_features[-4]}, {sorted_features[-3]}, {sorted_features[-2]}, and {sorted_features[-1]}"
    bottom_4_shap_perc = shap_means[-4:].sum() / shap_means.sum()

    demand_summary = f"**Demand Drivers**: The most important features in this last run were {top_features_text}, accounting for {_format_percentage(top_4_shap_perc)} of the variability in our SHAP values. The least important features were {bottom_features_text}, accounting for approximately {_format_percentage(bottom_4_shap_perc)} of our SHAP's variance."

    top_statistical_features = _search_list_for_substrings(
        string_list=sorted_shap_values.loc[: min(10, len(sorted_features)), "feature"],
        substr_list=["ewma_roll", "sum_roll", "mean_roll"],
    )
    count_statistical_features = len(top_statistical_features)
    statistical_features_shap_perc = (
        sorted_shap_values.loc[
            sorted_shap_values["feature"].isin(top_statistical_features), "value"
        ].sum()
        / shap_means.sum()
    )

    if statistical_features_shap_perc > 0.33:
        stat_recommendation = "Given the importance of statistical features in this last run, you may consider adding additional rolling funtions (e.g., skew, kurtosis) and/or window periods to your feature set for future runs."
        self.alerts["shap"] = stat_recommendation
    else:
        stat_recommendation = ""

    statistical_summary = f"**Statistical Features**: Statistical features make up {count_statistical_features} of the top {min(len(sorted_features), 10)} features, contributing {_format_percentage(statistical_features_shap_perc)} of this week's predicted values. {stat_recommendation}"

    output = "\n\n".join([demand_summary, statistical_summary])

    return output


## SHAP
def _calc_shap_values(self, data=None):
    """
    Calculaute SHAP values for use in various plots
    """
    if data is None:
        columns_to_keep = [
            col for col in self.model_object.history.columns if col != self.target
        ]

        data = _get_data_to_analyze(self=self)[columns_to_keep]

    explainer = shap.TreeExplainer(self.model_object)
    self.shap = {
        "explainer": explainer,
        "shap_values": explainer.shap_values(data),
        "data": data,
    }


def get_sorted_shap_values(self):
    if not hasattr(self, "shap"):
        _calc_shap_values(self=self)

    data = self.shap["data"]
    shap_values = self.shap["shap_values"]

    mean_shap_values = np.abs(shap_values).mean(0)

    feature_list = data.columns[np.argsort(np.abs(mean_shap_values))][::-1]
    feature_values = mean_shap_values[np.argsort(mean_shap_values)][::-1]

    return pd.DataFrame.from_dict({"feature": feature_list, "value": feature_values})


def _get_default_slicer(input_df):
    return list(range(min(len(input_df), 1000)))


def plot_shap_decision(self, slicer=None):
    """
    Plot a SHAP feature decision plot.

    Parameters
    -------------
    slicer : List[int], default None,
        A slace of rows to evaluate. Default uses the first 1000 rows.
    """
    if not hasattr(self, "shap"):
        _calc_shap_values(self=self)

    data = self.shap["data"]
    shap_values = self.shap["shap_values"]
    explainer = self.shap["explainer"]

    if slicer is None:
        slicer = _get_default_slicer(data)

    return shap.decision_plot(
        explainer.expected_value, shap_values[slicer], data.iloc[slicer, :]
    )


def plot_shap_importance(self, plot_type="dot"):
    """
    Plot a SHAP feature importance plot.

    Parameters
    ----------
    plot_type : str, default = "dot",
        What type of summary plot to produce. Note that "compact_dot" is only used for SHAP interaction values. Options are "dot" (default for single output), "bar" (default for multi-output), "violin", or "compact_dot".
    """
    if not hasattr(self, "shap"):
        _calc_shap_values(self=self)

    data = self.shap["data"]
    shap_values = self.shap["shap_values"]

    return shap.summary_plot(shap_values, data, plot_type=plot_type)


def plot_shap_dependence(self, column_name, color_column=None):

    if not hasattr(self, "shap"):
        _calc_shap_values(self=self)

    data = self.shap["data"]
    shap_values = self.shap["shap_values"]

    if not color_column:
        color_column = column_name

    return shap.dependence_plot(
        column_name,
        shap_values,
        data,
        interaction_index=color_column,
    )


def plot_shap_cohort(self, cohort):
    raise NotImplementedError(
        "Requires shap.Explainer to work with lightGBM models. See here: \
        https://shap.readthedocs.io/en/latest/example_notebooks/api_examples/plots/bar.html"
    )

    # explainer, shap_values, input_df = _assert_and_unpack_shap_values(self)

    # cohort = list(input_df[cohort])

    # return shap.plots.bar(
    #     shap_values.cohorts(cohort).abs.mean(0), show=show, *args, **kwargs
    # )


def plot_shap_waterfall(self, row):
    import shap

    if not hasattr(self, "shap"):
        _calc_shap_values(self=self)

    data = self.shap["data"]
    shap_values = self.shap["shap_values"]
    explainer = self.shap["explainer"]

    # hack to get waterfall api to work with TreeExplainer
    class ShapObject:
        def __init__(self, base_values, data, values, feature_names):
            self.base_values = base_values  # Single value
            self.data = data  # Raw feature values for 1 row of data
            self.values = values  # SHAP values for the same row of data
            self.feature_names = feature_names  # Column names

    shap_object = ShapObject(
        base_values=explainer.expected_value,
        values=explainer.shap_values(data)[row, :],
        feature_names=data.columns,
        data=data.iloc[row, :],
    )

    return shap.waterfall_plot(shap_object)


def plot_shap_force(self, slicer=None, show=False, *args, **kwargs):
    import shap

    shap.initjs()

    if not hasattr(self, "shap"):
        _calc_shap_values(self=self)

    data = self.shap["data"]
    shap_values = self.shap["shap_values"]
    explainer = self.shap["explainer"]

    if slicer is None:
        slicer = _get_default_slicer(data)

    return shap.force_plot(
        explainer.expected_value,
        shap_values[slicer, :],
        data.iloc[slicer, :],
    )


# Prophet
def plot_components(self, *args, **kwargs):
    """
    Plot the components of a prophet estimator
    """
    import fbprophet as prophet

    estimator = self.results["estimator"]
    forecast = self.predictions.reset_index()

    assert isinstance(
        estimator, prophet.forecaster.Prophet
    ), "This method only works with Prophet modeling objects."

    return estimator.plot_components(fcst=forecast, *args, **kwargs)


def _summarize_cv_errors(
    cv_errors,
    function=_calc_weighted_average,
    fold=-1,
    metric="Absolute Percent Error",
):
    """
    Return a dictionary containing summarized in-sample and out-of-sample metrics for a given fold
    """
    if function == _calc_weighted_average:
        summarized_errors = {
            key: function(values=value[metric], weights=value["Actuals"])
            for key, value in cv_errors[fold].items()
        }
    else:
        # Can also handle simple summary_functions, like pd.DataFrame.mean
        summarized_errors = {
            key: function(value[metric]) for key, value in cv_errors[fold].items()
        }

    return summarized_errors


def summarize_cv(self):
    """
    Summarize the fit of your fframe using a paragraph of automatically-generated text based on your out-of-sample error results.
    """

    def _get_threshold_dict():
        """
        Return a threshold dictionary used to map absolute percent errors to qualitative scores
        """
        from collections import OrderedDict

        return OrderedDict({"best": 0.10, "good": 0.15, "bad": 0.25, "worst": 1})

    def _score_absolute_percent_error(value):
        """Qualitatively score an absolute percent error metric"""

        threshold_dict = _get_threshold_dict()

        for key, threshold in threshold_dict.items():
            if value <= threshold:
                return key

    def _get_key_stats():
        return f"""
        <b>In-Sample {metric}</b>:
        <br />??? Median: {_format_percentage(is_median)}
        <br />??? Weighted Average: {_format_percentage(is_weighted_average)}
        <br />??? Difference: {_format_percentage((is_median-is_weighted_average))} ({is_skew} skew)
        <br /><br />

        <b>Out-of-Sample {metric}</b>:
                <br />??? Median: {_format_percentage(oos_median)}
                <br />??? Weighted Average: {_format_percentage(oos_weighted_average)}
                <br />??? Difference: {_format_percentage((oos_median-oos_weighted_average))} ({oos_skew} skew)
                <br /><br />
        """

    def _get_performance_summary():
        return f"For our last fold, our model achieved a median {_format_percentage(is_median)} in-sample {metric} and a {_format_percentage(oos_median)} out-of-sample {metric}. On a weighted average basis, our model achieved a {_format_percentage(is_weighted_average)} in-sample error and a {_format_percentage(oos_weighted_average)} out-of-sample error. The difference between our out-of-sample median and weighted average values suggests that our model is more accurate when predicting {oos_skew} values of our `{self.target}` variable."

    def _get_fit_summary():

        explainations = {
            "best": "well-tuned",
            "good": "well-tuned, with a slight hint of overfitting",
            "bad": "overfitting our training data",
            "worst": "significantly overfitting our training data",
        }

        return f"The {_format_percentage(difference)} error differential between our out-of-sample and in-sample results suggests that <b>our model is {explainations[difference_score]}</b>."

    def _get_recommendation_summary():

        overfitting_tips = """
            <ul>
                <li> Add more training data and/or resample your existing data </li>
                <li> Make sure that you're using a representative out-of-sample set when modeling </li>
                <li> Add noise or reduce the dimensionality of your feature set prior to modeling</li> 
                <li> Reduce the number of features you're feeding into your model </li>
                <li> Regularize your model using parameters like `lambda_l1`, `lambda_l2`,  `min_gain_to_split`, and `num_iterations`</li>
            </ul>
            """

        underfitting_tips = """
            <ul>
                <li> Add more training data and/or resample your existing data</li>
                <li> Add new features or modifying existing features based on insights from feature importance analysis</li> 
                <li> Reduce or eliminate regularization (e.g., decrease lambda, reduce dropout, etc.)</li>
            </ul>    
            """

        score_list = _get_threshold_dict().keys()
        not_best_conditions = score_list - ["best"]
        bad_conditions = score_list - ["best", "good"]

        # Build recommendation dictionary step-by-step, using oos_median and differnece_score as our keys
        # We're going to update keys at each step, where updates further down our code will overwrite earlier updates
        recommendation_dict = {}

        # oos_median == best & difference_score == best
        recommendation_dict.update(
            {
                (
                    "best",
                    "best",
                ): "We <b>wouldn't recommend any changes</b> to your modeling process at this time. Nice job!"
            }
        )

        # oos_median != best & difference_score == best
        recommendation_dict.update(
            {
                (
                    score,
                    "best",
                ): f"We <b>recommend making a few minor improvements</b> to control for underfitting: {underfitting_tips}"
                for score in not_best_conditions
            }
        )

        # oos_median == best & difference_score != best
        recommendation_dict.update(
            {
                (
                    "best",
                    difference,
                ): f"We <b>recommend making a few minor improvements</b> to control for overfitting: {overfitting_tips}"
                for difference in not_best_conditions
            }
        )

        # oos_median != best & difference_score != best
        recommendation_dict.update(
            {
                (
                    score,
                    difference,
                ): f"We <b>recommend controlling for overfitting</b>, then going back and working on your underfitting: {overfitting_tips}"
                for score in not_best_conditions
                for difference in not_best_conditions
            }
        )

        # difference_score == poor or worst
        recommendation_dict.update(
            {
                (
                    score,
                    difference,
                ): f"We <b>recommend making drastic improvements</b> to your approach to control for overfitting: {overfitting_tips}"
                for score in score_list
                for difference in bad_conditions
            }
        )

        # oos_median == poor or worst
        recommendation_dict.update(
            {
                (
                    score,
                    difference,
                ): f"We <b>recommend making drastic improvements</b> to your approach to control for underfitting. {underfitting_tips}"
                for score in bad_conditions
                for difference in score_list
            }
        )

        return recommendation_dict[(oos_score, difference_score)]

    metric = "Absolute Percent Error"

    cv_errors = self.get_cross_validation_errors(describe=False)

    # Weighted averages
    weighted_averages = _summarize_cv_errors(cv_errors=cv_errors, metric=metric)
    oos_weighted_average = weighted_averages["Out-of-Sample"]
    is_weighted_average = weighted_averages["In-Sample"]

    # Medians
    medians = _summarize_cv_errors(
        cv_errors=cv_errors, metric=metric, function=pd.DataFrame.median
    )
    oos_median = medians["Out-of-Sample"]
    is_median = medians["In-Sample"]

    # Score and skew
    oos_score = _score_absolute_percent_error(value=oos_median)
    is_skew = "left-tailed" if is_weighted_average < is_median else "right-tailed"
    oos_skew = "left-tailed" if oos_weighted_average < oos_median else "right-tailed"

    difference = abs(oos_median - is_median)
    difference_score = _score_absolute_percent_error(value=difference)

    key_stats = _get_key_stats()
    performance_summary = _get_performance_summary()
    fit_summary = _get_fit_summary()
    recommendation_summary = _get_recommendation_summary()

    return {
        "score": oos_score,
        "key_stats": key_stats,
        "performance": performance_summary,
        "recommendation": recommendation_summary,
    }


def plot_error_distributions(
    self,
    error_type="Absolute Percent Error",
    x_axis_title="",
    y_axis_title="",
    scheme="tealblues",
    height=75,
    width=300,
):
    """
    Plot an error distribution for each fold via altair
    """

    if not x_axis_title:
        x_axis_title = error_type

    def _get_errors_by_fold(self, error_type="Absolute Percent Error"):
        cv_errors = self.get_cross_validation_errors(describe=False)

        fold_df = []
        for index, fold in enumerate(cv_errors):
            for sample in ["In-Sample", "Out-of-Sample"]:
                df = fold[sample].loc[:, [error_type]].reset_index()
                df["Fold"] = index + 1
                df["Sample"] = sample
                fold_df.append(df)

        final_df = pd.concat(fold_df, axis=0)
        return final_df

    def _get_melted_fold_errors(self, error_type="Absolute Percent Error"):
        errors_df = _get_errors_by_fold(self=self, error_type=error_type)

        return pd.melt(
            errors_df, id_vars=["Fold", "Sample"], value_vars=[error_type]
        ).drop("variable", axis=1)

        # fold_df = [pd.concat([fold['In-Sample'][error_type].rename({error_type:"IS"}), fold['Out-of-Sample'][error_type]], axis=1) for fold in cv_errors]
        return final_df

    def _plot_melted_boxplot(
        melted_df,
        x_axis_title="",
        y_axis_title="",
        scheme="tealblues",
        height=75,
        width=300,
    ):

        # Schemes https://vega.github.io/vega/docs/schemes/#reference
        fig = (
            alt.Chart(melted_df)
            .mark_boxplot(outliers=False)
            .encode(
                y=alt.Column("Sample:O", title=y_axis_title),
                x=alt.Column("value:Q", title=x_axis_title),
                color=alt.Column(
                    "Fold:O",
                    title="",
                    legend=None,
                    scale=alt.Scale(scheme=scheme),
                ),
                row=alt.Column(
                    "Fold",
                    title="Folds",
                    header=alt.Header(labelAngle=1, labelFontSize=14, labelPadding=0),
                ),
            )
            .properties(width=width, height=height)
            .interactive()
        )

        return fig

    melted_df = _get_melted_fold_errors(self=self, error_type=error_type)

    return _plot_melted_boxplot(
        melted_df=melted_df,
        x_axis_title=x_axis_title,
        y_axis_title=y_axis_title,
        scheme=scheme,
        height=height,
        width=width,
    )


def plot_forward_predictions(self, width=400, height=300, scheme="tealblues"):
    """
    Plot forward-looking predictions
    """
    melted_data = (
        self.predictions.reset_index()
        .rename(
            {self.target: "Actuals", f"predicted_{self.target}": "Predictions"},
            axis=1,
        )
        .melt(
            id_vars=[self.datetime_column],
            value_vars=["Actuals", "Predictions"],
            var_name="Type",
            value_name="Values",
        )
    )

    fig = (
        alt.Chart(melted_data)
        .mark_line()
        .encode(
            x=f"{self.datetime_column}:T",
            y=f"Values",
            color=alt.Column(
                "Type:O",
                title="",
                scale=alt.Scale(scheme=scheme),
            ),
            strokeDash=alt.Column(
                "Type:O",
                title="",
            ),
            tooltip=[
                "Type",
                alt.Tooltip(
                    field="Values",
                    format=".2f",
                    type="quantitative",
                ),
                f"yearmonthdate({self.datetime_column})",
            ],
        )
        .configure_axis(grid=False)
        .configure_view(strokeWidth=0)
        .properties(width=width, height=height)
        .interactive()
    )

    return fig


def plot_predictions_over_time(
    self, fold=-1, width=400, height=300, scheme="tealblues"
):
    """
    Return a dictionary showing predictions and actuals over time for both "IS"
    and "OOS".

    Parameters
    ----------
    groupers : List[str], default None
        Optional parameter to create color labels for your grouping columns.
    """

    data = (
        _get_fold_predictions(self=self, fold=fold)
        .reset_index()
        .rename(
            {self.target: "Actuals", f"predicted_{self.target}": "Predictions"}, axis=1
        )
    )

    melted_data = data.melt(
        id_vars=[self.datetime_column, "Fold"],
        var_name="Type",
        value_name="Values",
    )

    fig = (
        alt.Chart(melted_data)
        .mark_line()
        .encode(
            x=f"{self.datetime_column}:T",
            y=f"Values",
            color=alt.Column(
                "Type:O",
                title="",
                scale=alt.Scale(scheme=scheme),
            ),
            strokeDash=alt.Column(
                "Fold:O",
                title="",
            ),
            tooltip=[
                "Fold:O",
                "Type",
                alt.Tooltip(
                    field="Values",
                    format=".2f",
                    type="quantitative",
                ),
                f"yearmonthdate({self.datetime_column})",
            ],
        )
        .configure_axis(grid=False)
        .configure_view(strokeWidth=0)
        .properties(width=width, height=height)
        .interactive()
    )

    return fig


def _get_fold_predictions(self, fold=-1):
    insample_df = self.cross_validations[fold]["train"][
        [self.target, f"predicted_{self.target}"]
    ].assign(Fold="In-Sample")

    oos_df = self.cross_validations[fold]["test"][
        [self.target, f"predicted_{self.target}"]
    ].assign(Fold="Out-of-Sample")

    return pd.concat([insample_df, oos_df], axis=0)


# Old plotting code (TODO delete)

# def _melt_dataframe_for_visualization(data, group_name, error):
#     filter_columns = [col for col in list(data.columns) if error in col]

#     return data[filter_columns].melt().assign(group=group_name)


# def _get_error_dict():
#     return {
#         "APE": "absolute percent error",
#         "RMSE": "root mean squared error",
#         "SE": "standard error",
#         "AE": "absolute error",
#     }


# def _check_error_input(error):
#     """Check that the given error has been implemented"""
#     acceptable_errors = _get_error_dict().keys()
#     assert (
#         error in acceptable_errors
#     ), f"Error metric not recognized; should be one of {acceptable_errors}"


# def _score_oos_error(value, error_type):
#     from collections import OrderedDict

#     threshold_dict = {
#         "APE": OrderedDict({"best": 0.05, "good": 0.10, "bad": 0.15, "worst": 1})
#     }

#     threshold_score = [
#         key
#         for key, threshold in threshold_dict[error_type].items()
#         if value <= threshold
#     ]

#     return threshold_score[0]


# def _score_oos_is_difference(value, error_type):
#     from collections import OrderedDict

#     threshold_dict = {
#         "APE": OrderedDict({"best": 0.10, "good": 0.15, "bad": 0.25, "worst": 1})
#     }

#     threshold_score = [
#         key
#         for key, threshold in threshold_dict[error_type].items()
#         if value <= threshold
#     ]

#     return threshold_score[0]


# def plot_fold_distributions(
#     self, groupers=None, error_type="APE", height=75, width=300, show=True
# ):
#     """
#     Return an altair boxplot of all of the error metrics visualized by fold

#     Parameters
#     ----------
#     groupers : list, default None
#         If a list of groupers is passed, it will calculate error metrics for a given
#         set of aggregated predictions stored in processed_outputs.
#     error_type : str, default "RMSE"
#         The error metric you'd like to plot by fold. Should be one of "APE",
#         "AE", "RMSE", or "SE".
#     height : int, default 75
#         The height of the altair plot to be shown
#     width : int, default 300
#         The height of the altair plot to be shown
#     show : bool, default True
#         Whether or not to render the final plot in addition to returning the altair object
#     """
#     _check_error_input(error_type)

#     if "fold_errors" not in dir(self):
#         self.calc_all_error_metrics(groupers=groupers)

#     combined_df = pd.concat(
#         [
#             _melt_dataframe_for_visualization(
#                 self.fold_errors[fold], group_name=f"Fold {fold + 1}", error=error_type
#             )
#             for fold, _ in self.fold_errors.items()
#         ],
#         axis=0,
#     )

#     plot = _plot_melted_boxplot(melted_df=combined_df, height=height, width=width)

#     if show:
#         plot

#     return plot


# def _plot_boxplot(
#     data, x_axis_title="", y_axis_title="", scheme="tealblues", height=75, width=300
# ):
#     fig = (
#         alt.Chart(data)
#         .mark_boxplot(outliers=False)
#         .encode(
#             x=alt.Column("variable:O", title=x_axis_title),
#             y=alt.Column("value:Q", title=y_axis_title),
#             color=alt.Column(
#                 "variable:O",
#                 title="",
#                 legend=None,
#                 scale=alt.Scale(scheme=scheme),
#             ),
#         )
#         .properties(height=height, width=width)
#         .interactive()
#     )

#     return fig


# def _plot_melted_boxplot(
#     melted_df,
#     x_axis_title="",
#     y_axis_title="",
#     scheme="tealblues",
#     height=75,
#     width=300,
# ):
#     # Schemes https://vega.github.io/vega/docs/schemes/#reference
#     fig = (
#         alt.Chart(melted_df)
#         .mark_boxplot(outliers=False)
#         .encode(
#             y=alt.Column("variable:O", title=y_axis_title),
#             x=alt.Column("value:Q", title=x_axis_title),
#             color=alt.Column(
#                 "group:O",
#                 title="",
#                 legend=None,
#                 scale=alt.Scale(scheme=scheme),
#             ),
#             row=alt.Column(
#                 "group",
#                 title="",
#                 header=alt.Header(labelAngle=1, labelFontSize=16, labelPadding=0),
#             ),
#         )
#         .properties(width=width, height=height)
#         .interactive()
#     )

#     return fig


# def plot_predictions_over_time(self, groupers=None):
#     """
#     Return a dictionary showing predictions and actuals over time for both "IS"
#     and "OOS".

#     Parameters
#     ----------
#     groupers : List[str], default None
#         Optional parameter to create color labels for your grouping columns.
#     """
#     output_dict = dict()
#     for sample in ["IS", "OOS"]:
#         data = _get_processed_outputs(self=self, sample=sample, groupers=groupers)

#         # altair doesn't handle categoricals
#         converted_data = _convert_nonnumerics_to_objects(data)

#         output_dict[sample] = _plot_lineplot_over_time(
#             data=converted_data, groupers=groupers
#         )

#     return output_dict


# def _plot_lineplot_over_time(data, groupers):
#     """Plots predictions vs. actuals over time."""
#     import altair as alt

#     if groupers:
#         data["group"] = data[groupers].apply(
#             lambda row: "/".join(row.values.astype(str)), axis=1
#         )

#         # altair throws object errors if other columns are serialized
#         data = data[["Date", "Values", "Label", "group"]]

#         fig = (
#             alt.Chart(data)
#             .mark_line()
#             .encode(
#                 x="Date:T",
#                 y="Values",
#                 color="group:O",
#                 strokeDash="Label",
#                 tooltip=[
#                     "group:O",
#                     "Label",
#                     alt.Tooltip(
#                         field="Values",
#                         format=".2f",
#                         type="quantitative",
#                     ),
#                     "yearmonthdate(Date)",
#                 ],
#             )
#             .configure_axis(grid=False)
#             .configure_view(strokeWidth=0)
#             .interactive()
#         )
#     else:
#         # altair throws object errors if other columns are serialized
#         data = data[["Date", "Values", "Label"]]
#         data["Date"] = pd.to_datetime(data["Date"])

#         fig = (
#             alt.Chart(data)
#             .mark_line()
#             .encode(
#                 x="Date:T",
#                 y="Values",
#                 strokeDash="Label",
#                 tooltip=[
#                     "Label",
#                     alt.Tooltip(
#                         field="Values",
#                         format=".2f",
#                         type="quantitative",
#                     ),
#                     "yearmonthdate(Date)",
#                 ],
#             )
#             .configure_axis(grid=False)
#             .configure_view(strokeWidth=0)
#             .interactive()
#         )

#     return fig


# def summarize_performance_over_time(self, error_type="APE", period="month"):
#     """
#     Summarize the findings of our k-fold cross-validation

#     Parameters
#     ----------
#     error_type : str, default "RMSE"
#         The error metric you'd like to plot by fold. Should be one of "APE",
#         "AE", "RMSE", or "SE".

#     """

#     def _get_seasonality_summary(self):
#         def _convert_int_to_month(integer):
#             return datetime.date(1900, integer, 1).strftime("%B")

#         target_sum_by_month = self.data.groupby(self.data.index.month)[
#             self.target
#         ].sum()
#         target_sum_by_month.sort_values(ascending=False, inplace=True)

#         agg_spike_period = target_sum_by_month.idxmax()
#         agg_spike = target_sum_by_month[agg_spike_period]
#         neg_agg_spike_period = target_sum_by_month.idxmin()
#         neg_agg_spike = target_sum_by_month[neg_agg_spike_period]

#         return f"**Seasonality**: Over the past year, we've seen aggregate {self.target} reach as high as {agg_spike} during the {period} of {_convert_int_to_month(agg_spike_period)} while dropping down to {neg_agg_spike} during {_convert_int_to_month(neg_agg_spike_period)}. "

#     max_fold = _get_max_fold(self)

#     today = max(self.data.index)
#     last_month = today - datetime.timedelta(days=30)
#     last_2_months = today - datetime.timedelta(days=60)
#     last_3_months = today - datetime.timedelta(days=90)
#     last_year = today - datetime.timedelta(days=365)
#     last_year_plus_1_month = today - datetime.timedelta(days=335)
#     last_year_minus_1_month = today - datetime.timedelta(days=395)

#     def _get_target_trends(self):
#         def _calc_percent_change(new, old):
#             return (new - old) / old

#         sum_target_two_months_ago = self.data.loc[
#             (self.data.index >= last_2_months) & (self.data.index <= last_month),
#             self.target,
#         ].sum()
#         sum_target_last_month = self.data.loc[
#             (self.data.index >= last_month) & (self.data.index <= today),
#             self.target,
#         ].sum()
#         target_growth_prior_month = _calc_percent_change(
#             sum_target_last_month, sum_target_two_months_ago
#         )
#         growth_sign = "grew" if target_growth_prior_month > 0 else "fell"

#         sum_target_last_year = self.data.loc[
#             (self.data.index >= (last_month - datetime.timedelta(days=365)))
#             & (self.data.index <= (today - datetime.timedelta(days=365))),
#             self.target,
#         ].sum()
#         yoy_growth = _calc_percent_change(sum_target_last_month, sum_target_last_year)
#         diff_sign = "up" if yoy_growth > 0 else "down"

#         summary = f"**Trends**: Sales {growth_sign} by {target_growth_prior_month} last month, {diff_sign} {yoy_growth} over the previous year. We expect sales to continue trending upwards in the coming month."
#         return summary

#     output = "\n\n".join(
#         [
#             _get_target_trends(self),
#             _get_seasonality_summary(self),
#         ]
#     )

#     return output
