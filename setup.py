from setuptools import setup, find_packages
import vaultaic
import io


with io.open("README.md", encoding="utf-8") as f:
    long_description = f.read()

with io.open("requirements.txt", encoding="utf-8") as f:
    requirements = [r for r in f.read().split('\n') if len(r)]

setup(name="vaultaic",
      version=vaultaic.__version__,
      description="",
      long_description=long_description,
      long_description_content_type="text/markdown",
      url="",
      author="Antoine Poinsot",
      author_email="darosior@protonmail.com",
      license="MIT",
      packages=find_packages(),
      keywords=["bitcoin", "vault"],
      #install_requires=requirements
      )
