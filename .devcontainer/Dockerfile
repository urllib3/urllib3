FROM ubuntu:20.04

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# Ensure apt is in non-interactive to avoid prompts
ENV DEBIAN_FRONTEND=noninteractive

# Create the user
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    #
    # [Optional] Add sudo support. Omit if you don't need to install software after connecting.
    && apt-get update \
    && apt-get install -y sudo \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

RUN rm -f /etc/apt/apt.conf.d/docker-clean; echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

# Install dependencies.
RUN --mount=type=cache,target=/var/cache/apt --mount=type=cache,target=/var/lib/apt \
    apt-get update && apt-get -y install --no-install-recommends \
    build-essential make libssl-dev zlib1g-dev libbz2-dev \
    libreadline-dev libsqlite3-dev curl llvm libncursesw5-dev \
    xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \
    wget ca-certificates apt-utils locales git openssh-client && \
    locale-gen en_US.UTF-8

ENV DEBIAN_FRONTEND=dialog

USER $USERNAME

# Install pyenv to manage multiple python installations
RUN curl -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash && \
    echo 'export PATH="$HOME/.pyenv/bin:$PATH"' >> ~/.bashrc && \
    echo 'eval "$(pyenv init --path)"' >> ~/.bashrc && \
    echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc

# Not sure this is needed
SHELL ["/bin/bash","--login", "-c"]

# Stuff needed to make pyenv work correctly since the login shell
# above doesnt seem to run bachrc
ENV PYENV_ROOT="/home/vscode/.pyenv"
ENV PATH $PYENV_ROOT/shims:$PYENV_ROOT/bin:$PATH


# Install the required python versions (this takes a bit usually) so we do lots of cacheing
RUN --mount=type=cache,target=/home/vscode/.pyenv/cache,uid=1000 \
    pyenv install -s 3.7.13 && \
    pyenv install -s 3.8.13 && \
    pyenv install -s 3.9.12 && \
    pyenv install -s 3.10.4 && \
    pyenv global 3.9.12 && \
    pyenv rehash


# Install project dependencies that are specific to the devcontainer
RUN pip install --user --upgrade nox pre-commit black flake8 flake8-2020 isort
