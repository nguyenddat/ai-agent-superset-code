FROM apache/superset:6.1.0

USER root
RUN uv pip install --python /app/.venv/bin/python \
    psycopg2-binary==2.9.10 \
    sqlglot==28.10.1 \
    'pydantic-settings>=2.0,<3' \
    'langchain>=1.1,<2' \
    'langchain-openai>=1.1,<2' \
    'langgraph>=1.1,<2' \
    'fastmcp>=2.13,<3'
USER superset
