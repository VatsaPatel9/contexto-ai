"""Vision processing for extracting educational content from document images.

Uses OpenAI's vision-capable models to describe diagrams, flowcharts, tables,
equations, and other informative visuals. Decorative images are skipped.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import openai

logger = logging.getLogger(__name__)

_VISION_PROMPT = """You are analyzing an image from an educational document titled "{doc_title}".

If this image contains meaningful educational content (diagram, flowchart, chart, \
table, equation, scientific illustration, architecture diagram, process flow, \
graph, or any informative visual), describe it in detail:
- What does it show?
- What are the key components, labels, or steps?
- What concept does it illustrate?
- Transcribe any visible text, labels, or values exactly as they appear.

If this image is decorative, a logo, a design element, a background pattern, \
a photograph of a person or object that does not illustrate an educational concept, \
or otherwise not meaningful to the educational content, respond with exactly: SKIP

Respond in plain text only. No markdown formatting."""


class VisionProcessor:
    """Send document images to an OpenAI vision model for description."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.model = model
        self._client = openai.OpenAI(api_key=api_key)

    def describe_image(
        self,
        image_bytes: bytes,
        doc_title: str = "",
    ) -> Optional[str]:
        """Describe an image using the vision model.

        Returns the text description, or ``None`` if the image is not
        meaningful (model responded with SKIP) or an error occurred.
        """
        try:
            b64_image = base64.b64encode(image_bytes).decode("utf-8")

            # Use max_completion_tokens for newer models, fall back to max_tokens
            token_param = (
                {"max_completion_tokens": 500}
                if "gpt-5" in self.model or "o3" in self.model or "o4" in self.model
                else {"max_tokens": 500}
            )

            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": _VISION_PROMPT.format(doc_title=doc_title),
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64_image}",
                                    "detail": "low",
                                },
                            },
                        ],
                    }
                ],
                temperature=0.2,
                **token_param,
            )

            text = (response.choices[0].message.content or "").strip()

            if text.upper() == "SKIP" or not text:
                return None

            return text

        except openai.APIError as exc:
            logger.warning("Vision API error: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Vision processing error: %s", exc)
            return None

    def process_images(
        self,
        images: list[dict],
        doc_title: str = "",
    ) -> list[dict]:
        """Process a batch of extracted images and return descriptions.

        Args:
            images: List of dicts from ``extract_pdf_images()`` with keys
                ``image_bytes``, ``page_num``, ``index``.
            doc_title: Document title for context in the vision prompt.

        Returns:
            List of dicts with keys ``description``, ``page_num``, ``index``
            for images that contained meaningful content. Decorative images
            are filtered out.
        """
        results: list[dict] = []

        for img in images:
            logger.info(
                "Vision: processing image %d from page %d (%d bytes)",
                img["index"], img["page_num"], len(img["image_bytes"]),
            )

            description = self.describe_image(
                image_bytes=img["image_bytes"],
                doc_title=doc_title,
            )

            if description is None:
                logger.info("Vision: image %d skipped (decorative/not meaningful)", img["index"])
                continue

            logger.info(
                "Vision: image %d described (%d chars)",
                img["index"], len(description),
            )

            results.append({
                "description": description,
                "page_num": img["page_num"],
                "index": img["index"],
            })

        logger.info(
            "Vision: %d/%d images contained meaningful content",
            len(results), len(images),
        )

        return results
