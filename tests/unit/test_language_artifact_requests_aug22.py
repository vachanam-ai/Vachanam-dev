import pytest

from agent.livekit_minimal.agent import _explicit_language_request


LANGUAGES = (
    ("English", "en"),
    ("Telugu", "te"),
    ("Hindi", "hi"),
    ("Tamil", "ta"),
    ("Kannada", "kn"),
    ("Malayalam", "ml"),
    ("Marathi", "mr"),
    ("Bengali", "bn"),
)


@pytest.mark.parametrize(("language", "_code"), LANGUAGES)
@pytest.mark.parametrize("template", (
    "prescription in {language}",
    "medical report in {language}",
    "send document in {language}",
    "write medicine name in {language}",
))
def test_artifact_language_does_not_switch_the_spoken_call(
    language,
    _code,
    template,
):
    assert _explicit_language_request(
        template.format(language=language)
    ) is None


@pytest.mark.parametrize(("language", "code"), LANGUAGES)
@pytest.mark.parametrize("template", (
    "Speak in {language} while we discuss the prescription.",
    "Please answer in {language} about my medical report.",
    "Continue in {language} for this conversation about the document.",
))
def test_spoken_language_command_still_wins_with_artifact_context(
    language,
    code,
    template,
):
    assert _explicit_language_request(
        template.format(language=language)
    ) == code


@pytest.mark.parametrize(("language", "code"), LANGUAGES)
def test_final_short_spoken_language_choice_overrides_artifact_language(
    language,
    code,
):
    assert _explicit_language_request(
        f"Send the document in English. {language} please."
    ) == code
