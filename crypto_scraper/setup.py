from setuptools import setup, find_packages

setup(
    name="crypto_scraper",
    version="1.0",
    packages=find_packages(),
    install_requires=["scrapy>=2.11"],
    entry_points={"scrapy": ["settings = crypto_scraper.settings"]},
)
