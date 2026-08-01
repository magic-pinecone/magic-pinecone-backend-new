FROM ubuntu:latest
LABEL authors="spig1"

ENTRYPOINT ["top", "-b"]