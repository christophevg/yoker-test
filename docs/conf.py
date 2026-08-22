"""Sphinx configuration for yoker-test documentation."""

project = "yoker-test"
copyright = "2025, Christophe VG"
author = "Christophe VG"

extensions = [
  "myst_parser",
]

source_suffix = [".rst", ".md"]
master_doc = "index"
html_theme = "sphinx_rtd_theme"