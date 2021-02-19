from setuptools import setup, find_packages

setup(
    name="ForecastFrame",
    maintainer="Nick Lind",
    version="1.0",
    packages=find_packages(include=["forecastframe"]),
    maintainer_email="nick@quantilegroup.com",
    description="Granular, accurate, and interpretable forecasting made easy",
    platforms="any",
    python_requires=">=3.6.1",
)
