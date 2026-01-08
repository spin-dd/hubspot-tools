FROM python
ARG BASE
#
RUN apt-get update
RUN apt-get -y install \
    locales \
    less \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* 
#
RUN localedef -f UTF-8 -i ja_JP ja_JP.UTF-8
ENV LANG ja_JP.UTF-8 
ENV LANGUAGE ja_JP:ja
ENV LC_ALL ja_JP.UTF-8
ENV TZ JST-9
ENV TERM xterm

# uv
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"
ENV UV_COMPILE_BYTCODE=1 \
    UV_CAHE_DIR=/root/.cache/uv \
    UV_LINK_MODE=copy


COPY src ${BASE}/src
COPY pyproject.toml ${BASE}/pyproject.toml
COPY uv.lock ${BASE}/uv.lock
COPY README.md ${BASE}/README.md

WORKDIR ${BASE}

#
RUN uv sync --python-preference only-system
CMD ["sleep", "infinity"]