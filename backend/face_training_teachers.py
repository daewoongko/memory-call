"""Differentiable training-only judges for face re-aging experiments.

These networks are never used by the web service.  They provide gradients to
FRAN while it is being adapted, then the existing production inference stack
continues to run unchanged.
"""

from __future__ import annotations

import torch
from torch import nn
from torchvision.models import ResNet18_Weights, resnet18


AGE_CLASSES = 101


class AgeTeacher(nn.Module):
    """A Korean-face age estimator with a differentiable expected-age head."""

    def __init__(self, *, pretrained: bool = True, embedding_dim: int = 256):
        super().__init__()
        weights = ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
        backbone = resnet18(weights=weights)
        feature_dim = int(backbone.fc.in_features)
        backbone.fc = nn.Identity()
        self.backbone = backbone
        self.embedding = nn.Sequential(
            nn.Linear(feature_dim, embedding_dim),
            nn.BatchNorm1d(embedding_dim),
        )
        self.age_head = nn.Linear(feature_dim, AGE_CLASSES)
        self.register_buffer(
            "age_values", torch.arange(AGE_CLASSES, dtype=torch.float32), persistent=False
        )

    def forward(self, images: torch.Tensor) -> dict[str, torch.Tensor]:
        features = self.backbone(images)
        logits = self.age_head(features)
        probabilities = logits.softmax(dim=1)
        expected_age = (probabilities * self.age_values[None]).sum(dim=1)
        embedding = nn.functional.normalize(self.embedding(features), dim=1)
        return {
            "logits": logits,
            "expected_age": expected_age,
            "embedding": embedding,
        }


class IdentityTeacher(nn.Module):
    """Training-only face embedding adapted with within-family hard negatives."""

    def __init__(self, *, pretrained: bool = True, embedding_dim: int = 256):
        super().__init__()
        weights = ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
        backbone = resnet18(weights=weights)
        feature_dim = int(backbone.fc.in_features)
        backbone.fc = nn.Identity()
        self.backbone = backbone
        self.embedding = nn.Sequential(
            nn.Linear(feature_dim, embedding_dim),
            nn.BatchNorm1d(embedding_dim),
        )

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return nn.functional.normalize(self.embedding(self.backbone(images)), dim=1)


def load_age_teacher(path: str, device: torch.device | str = "cpu") -> AgeTeacher:
    payload = torch.load(path, map_location=device, weights_only=True)
    state = payload.get("model", payload) if isinstance(payload, dict) else payload
    model = AgeTeacher(pretrained=False).to(device)
    model.load_state_dict(state, strict=True)
    model.eval()
    return model

def load_identity_teacher(path: str, device: torch.device | str = "cpu") -> IdentityTeacher:
    payload = torch.load(path, map_location=device, weights_only=True)
    state = payload.get("model", payload) if isinstance(payload, dict) else payload
    model = IdentityTeacher(pretrained=False).to(device)
    model.load_state_dict(state, strict=True)
    model.eval()
    return model
