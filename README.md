# 🧩 Wordle Solver

An advanced **Wordle Solver** built in Python, capable of solving single or multiple Wordle puzzles simultaneously.
It features smart guessing algorithms, interactive feedback handling, and a **benchmarking suite** with heatmap analytics.

---
* **Multiple Game Modes**:

  * **Multi-Word Solver** – Solve multiple words in parallel with shared guesses.
  * **Sequence Solver** – Solve words one by one with adaptive feedback.
  * **Test Mode** – Automatically benchmark solver performance on all words.

* **Word Scoring Algorithm**
  Uses letter frequency analysis to rank the best guesses.

  Accepts feedback using:

  * `g` = green (correct letter & position)
  * `y` = yellow (correct letter, wrong position)
  * `b`, `x` = black/gray (letter not in word)

* **Benchmarking & Analytics**

  * Tests solver performance against all words.
  * Displays **letter frequency heatmaps** using `matplotlib` and `seaborn`.

---

## 🚀 Getting Started

### **1. Clone this Repository**

```
git clone https://github.com/your-username/Wordle-Solver.git
cd Wordle-Solver
```

### **2. Install Dependencies**

```
pip install -r requirements.txt
```

**Dependencies:**

* `pandas`
* `numpy`
* `matplotlib`
* `seaborn`

### **3. Run the Solver**

```
python wordle_main.py
```

---

## 🎮 Game Modes

When running `wordle_main.py`, you'll be prompted to choose a mode:

1. **Multi-Word Solver (Parallel solving)**
2. **Sequence Solver (One word at a time)**
3. **Test Solver on All Words**
4. **Exit**

---

## 🧪 Benchmarking

You can run the test suite to benchmark opener sets and solver performance:

```
python test_suite.py
```

This will:

* Evaluate a list of opener guesses (e.g., `AROSE`, `LINTY`, `CHUMP`).
* Show success rate and average guesses.
* Generate a heatmap of letter frequency by position.

---

## 📂 Project Structure

```
Wordle-Solver/
│── wordle_main.py         # Main entry point
│── constants.py           # Global constants (word length, feedback codes)
│── loader.py              # Loads the word list
│── interface.py           # Handles user input (game modes, openers)
│── helpers.py             # Utility functions (scoring, top suggestions)
│── filtering.py           # Feedback-based word filtering
│── scoring.py             # Word scoring logic
│── test_suite.py          # Benchmarking & analytics
│── modes/
│    ├── multi_solver.py   # Multi-word solver
│    └── sequence_solver.py # Sequential solver
└── wordle_words.csv       # Word list
```

---
## 🛠 Changing Opening Suggestions

Default opener sets are defined as **global variables** at the top of `interface.py`:

```python
# interface.py

# === GLOBAL OPENER CONFIGURATION ===
DEFAULT_OPENERS = [
    ["arose"],                  # Option 1
    ["arose", "linty"],         # Option 2
    ["arose", "linty", "chump"] # Option 3
]
```

### **How to Change Them**

1. Open `interface.py`.
2. Modify `DEFAULT_OPENERS` to include your preferred starting words.
   For example:

   ```python
   DEFAULT_OPENERS = [
       ["trace"],                  # Option 1
       ["trace", "pound"],         # Option 2
       ["trace", "pound", "silky"] # Option 3
   ]
   ```
3. Save the file. The game will automatically show your updated opener sets when you run the solver.

### **Rescue Mode**

You can still select **Option 4 (Rescue Mode)** at runtime to manually input custom opener guesses without editing the file.

---

## 🔧 Configuration

* **Word List**: Defined in `constants.py` as `WORD_LIST_PATH`.
* **Openers**: Default openers (`AROSE`, `LINTY`, `CHUMP`) can be updated in `interface.py`.
* **Feedback Options**: Feedback characters `g`, `y`, `b` are handled in `helpers.py`.

---

## 📊 Example Output

**Benchmarking Example:**

```
📊 Test Summary for Openers: ['arose', 'linty', 'chump']
✅ Solved: 2290/2315
📈 Avg Guesses for Solved: 3.65
```

---

## 🤝 Contributing

Contributions are welcome!
Feel free to fork this repository, submit issues, or open pull requests with improvements.

---

## ⚡ Fun Fact

This solver can crack most Wordle challenges in **3-4 guesses on average** using optimized opener sets.

---

## 📬 Contact

Created by **George (@geosaurus98)**

* 📧 [george.johnson@outlook.co.nz](mailto:george.johnson@outlook.co.nz)
* 🔗 [LinkedIn](https://www.linkedin.com/in/george-johnson-nz)

---
