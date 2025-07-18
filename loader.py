# loader.py
"""
Handles loading the word list from a CSV file.
"""

import pandas as pd
from constants import WORD_LIST_PATH

def load_word_list(filepath=WORD_LIST_PATH):
    """
    Loads and returns a list of lowercase words from a CSV file.

    Args:
        filepath (str): Path to the CSV file.

    Returns:
        list[str]: List of 5-letter lowercase words.
    """
    df = pd.read_csv(filepath, header=None)
    return df[0].str.lower().tolist()