"""
Fake agent outputs used by the tests.

They imitate what the four real agents write, so the whole pipeline
(parsing -> validation -> Markdown -> database -> API) can be tested
without calling CrewAI or Groq.
"""

from app.services.crewai_service import CrewRawOutput

COORDINATOR_TEXT = """\
### Teaching Plan
1. Explain what an API is.
2. Introduce FastAPI and why it is fast to write.
3. Build a tiny endpoint.
4. Show automatic validation and docs.

### Key Concepts
- API: a way for programs to talk to each other
- Endpoint: a URL that does one job
- Validation: checking incoming data
- Interactive docs: auto-generated test page

### Questions
Q1: What is FastAPI?
Q2: How does FastAPI validate incoming data?
Q3: When would a beginner choose FastAPI?
"""

EXPLANATION_TEXT = """\
### What is FastAPI?
FastAPI is a Python framework for building web APIs. An API (Application Programming
Interface) is a way for two programs to talk to each other over the internet. FastAPI
helps you write these APIs with very little code.

### How it works
You write normal Python functions and add a decorator that says which URL should call
them. FastAPI reads the type hints in your function and uses them to validate data.

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/hello")
def hello():
    return {"message": "Hello!"}
```

1. `FastAPI()` creates the application.
2. `@app.get("/hello")` connects the URL `/hello` to the function.
3. The function returns a dictionary, which FastAPI turns into JSON.

### Why it is useful
It is useful because it checks data for you and creates interactive documentation
automatically, which saves beginners a lot of time.
END_OF_EXPLANATION
"""

QA_TEXT = """\
Q1: What is FastAPI?
A1: FastAPI is a Python framework for building web APIs with very little code.

Q2: How does FastAPI validate incoming data?
A2: It reads the type hints in your function and uses them to validate data.

Q3: When would a beginner choose FastAPI?
A3: When they want data checking and interactive documentation created automatically.
"""

SUMMARY_TEXT = """\
- FastAPI is a Python framework for building web APIs.
- An API lets two programs talk to each other.
- Decorators like @app.get connect URLs to Python functions.
- Type hints let FastAPI validate incoming data automatically.
- FastAPI generates interactive documentation for you.
"""


def good_crew_output() -> CrewRawOutput:
    return CrewRawOutput(
        coordinator=COORDINATOR_TEXT,
        explanation=EXPLANATION_TEXT,
        qa=QA_TEXT,
        summary=SUMMARY_TEXT,
    )


def fake_successful_crew(topic, on_task_complete=None, settings=None):
    """Behaves like run_learning_crew: reports 4 steps, returns outputs."""
    for step in range(1, 5):
        if on_task_complete:
            on_task_complete(step)
    return good_crew_output()
