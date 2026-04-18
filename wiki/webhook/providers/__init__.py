"""Git provider webhook payload parsers."""

from wiki.webhook.providers.gitea import GiteaWebhookParser
from wiki.webhook.providers.github import GitHubWebhookParser
from wiki.webhook.providers.gitlab import GitLabWebhookParser

__all__ = [
    "GiteaWebhookParser",
    "GitHubWebhookParser",
    "GitLabWebhookParser",
]
