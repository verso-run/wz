# A clean Ubuntu with only what a fresh desktop has: curl and CA certificates. No git, no Python, no tmux, no sudo.
FROM ubuntu:24.04
RUN apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null && rm -rf /var/lib/apt/lists/*
RUN useradd -m -s /bin/bash tester
USER tester
WORKDIR /home/tester
ENV SHELL=/bin/bash
