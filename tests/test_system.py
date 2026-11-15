import unittest
from app.browser_assistant import detect_ats, validate_public_url, adapter_metadata
from app.orchestration import infer_stage, field_requirements
from app.scoring import score_job

class SystemTests(unittest.TestCase):
    def test_ats_detection(self):
        self.assertEqual(detect_ats("https://boards.greenhouse.io/acme/jobs/1"),"greenhouse")
        self.assertEqual(detect_ats("https://jobs.lever.co/acme/123"),"lever")
        self.assertEqual(detect_ats("https://jobs.ashbyhq.com/acme/123"),"ashby")
        self.assertEqual(detect_ats("https://docs.google.com/forms/d/e/x/viewform"),"google_forms")
        self.assertEqual(detect_ats("https://example.org/apply"),"generic")

    def test_adapter_capability_is_not_overstated(self):
        self.assertEqual(adapter_metadata("greenhouse")["submission_api"],"employer_api_key_required")
        self.assertEqual(adapter_metadata("workday")["level"],"generic_accessible_form")

    def test_non_https_rejected(self):
        for url in ["http://example.com/apply","file:///etc/passwd","https://localhost/apply","https://127.0.0.1/apply"]:
            with self.assertRaises(ValueError): validate_public_url(url)

    def test_remote_alone_does_not_imply_nigeria_eligibility(self):
        _,_,eligibility,_=score_job("Product Manager","Remote","Remote role; location restrictions not stated.")
        self.assertEqual(eligibility,"verify")

    def test_nigeria_specific_remote_role_is_likely_not_guaranteed(self):
        _,_,eligibility,reasons=score_job("Associate Product Manager","Remote Nigeria","Applicants based in Nigeria may apply.")
        self.assertEqual(eligibility,"likely")
        self.assertIn("verify",reasons.lower())

    def test_workflow_does_not_misclassify_visible_submit_footer(self):
        r=infer_stage("Work experience","https://jobs.example.org", [{"label":"Employment history"}],
                      [{"text":"Continue"},{"text":"Submit application"}])
        self.assertEqual(r["stage"],"experience")
        self.assertEqual(len(r["next_step_controls"]),1)
        self.assertEqual(len(r["final_submission_controls"]),1)

    def test_required_fields_skip_disabled_and_hidden(self):
        r=field_requirements([
          {"label":"Email","required":True},
          {"label":"Hidden","required":True,"type":"hidden"},
          {"label":"Disabled","required":True,"disabled":True}])
        self.assertEqual([x["label"] for x in r],["Email"])

if __name__=="__main__":unittest.main()

class QualificationEvidenceTests(unittest.TestCase):
    def test_location_evidence_is_retained_and_restricted_is_separate_from_hard_exclusion(self):
        from app.scoring import score_job_detailed
        _,_,eligibility,_,evidence=score_job_detailed(
            'Product Manager','Remote - UK','Applicants must be based in the United Kingdom. Visa sponsorship available.')
        self.assertEqual(eligibility,'restricted')
        self.assertTrue(any('united kingdom' in x['quote'].lower() for x in evidence))
        _,_,hard,_,_=score_job_detailed('Analyst','Remote','US citizens only; active security clearance required.')
        self.assertEqual(hard,'ineligible')

class HybridScoringTests(unittest.TestCase):
    def test_ambiguous_role_uses_ai_track_without_ai_score(self):
        from unittest.mock import patch
        from app.scoring import score_job_detailed
        result = {
            "track": "Strategy", "opportunity_type": "Other", "confidence": 0.92,
            "evidence": ["Own strategic planning and business operations."],
        }
        with patch("app.ai_classifier.settings.enable_ai_classification", True), \
             patch("app.scoring.classify_ambiguous_opportunity", return_value=result) as mocked:
            score, track, eligibility, reasons, evidence = score_job_detailed(
                "Programme Lead", "Remote", "Own strategic planning and business operations."
            )
        mocked.assert_called_once()
        self.assertEqual(track, "Strategy")
        self.assertNotEqual(score, 65)
        self.assertEqual(eligibility, "verify")
        self.assertIn("AI-assisted interpretation", reasons)
        self.assertTrue(any(item["type"] == "ai_interpretation" for item in evidence))

    def test_strong_title_signal_skips_ai(self):
        from unittest.mock import patch
        from app.scoring import score_job_detailed
        with patch("app.scoring.classify_ambiguous_opportunity") as mocked:
            _, track, _, _, _ = score_job_detailed(
                "Associate Product Manager", "Nigeria", "Build product roadmaps and work with engineers."
            )
        mocked.assert_not_called()
        self.assertEqual(track, "Product")

    def test_africa_and_remote_do_not_confirm_nigeria(self):
        from app.scoring import score_job
        _, _, eligibility, _ = score_job(
            "Product Manager", "Remote Africa", "This remote role is open to applicants across Africa."
        )
        self.assertEqual(eligibility, "verify")

    def test_country_restriction_overrides_generic_remote_signal(self):
        from app.scoring import score_job
        _, _, eligibility, _ = score_job(
            "Product Manager", "Remote", "Remote role. Applicants must be based in the United Kingdom."
        )
        self.assertEqual(eligibility, "restricted")

    def test_ai_result_validation_rejects_unknown_taxonomy(self):
        from app.ai_classifier import _normalise_result
        self.assertIsNone(_normalise_result({"track": "Magic", "opportunity_type": "Internship"}))

    def test_ai_result_validation_normalises_confidence(self):
        from app.ai_classifier import _normalise_result
        result = _normalise_result({"track": "Strategy", "opportunity_type": "Other", "confidence": 4})
        self.assertEqual(result["confidence"], 1.0)

    def test_explicit_non_nigeria_restriction_overrides_location_hint(self):
        from app.scoring import score_job
        _, _, eligibility, _ = score_job(
            "Product Manager", "Nigeria / Remote", "Applicants must be based in the United Kingdom."
        )
        self.assertEqual(eligibility, "restricted")

    def test_explicit_nigeria_acceptance_can_resolve_geography(self):
        from app.scoring import score_job
        _, _, eligibility, _ = score_job(
            "Product Manager", "Remote", "Applicants based in Nigeria may apply."
        )
        self.assertEqual(eligibility, "likely")

class AIClassificationDisabledByDefaultTests(unittest.TestCase):
    def test_classifier_does_not_call_openai_when_disabled(self):
        from unittest.mock import patch
        from app import ai_classifier
        with patch.object(ai_classifier.settings, "enable_ai_classification", False), \
             patch.object(ai_classifier, "_classify_cached") as mocked:
            result = ai_classifier.classify_ambiguous_opportunity(
                "Programme Lead", "Remote", "Own strategic planning and business operations."
            )
        self.assertIsNone(result)
        mocked.assert_not_called()

class AIClassifierClientTests(unittest.TestCase):
    def test_classifier_uses_structured_output_and_validates_source_evidence(self):
        import sys
        import types
        from unittest.mock import patch
        from app import ai_classifier

        captured = {}
        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                content = '{"track":"Strategy","opportunity_type":"Other","seniority":"Early-career","work_mode":"Remote","geographic_eligibility":"Unclear","eligible_countries":[],"required_experience":"Not specified","key_requirements":[],"evidence":["Build business operations" , "Invented quote"],"confidence":0.9}'
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])
        class FakeClient:
            def __init__(self, **kwargs):
                self.chat = types.SimpleNamespace(completions=FakeCompletions())
        fake_module = types.SimpleNamespace(OpenAI=FakeClient)
        with patch.object(ai_classifier, "settings") as patched_settings, \
             patch.dict(sys.modules, {"openai": fake_module}):
            patched_settings.openai_api_key = "test-key"
            patched_settings.enable_ai_classification = True
            patched_settings.openai_classifier_model = "gpt-6-luna"
            ai_classifier.clear_classifier_cache()
            result = ai_classifier.classify_ambiguous_opportunity(
                "Programme Lead", "Remote", "Build business operations for a distributed team."
            )
        self.assertEqual(result["track"], "Strategy")
        self.assertEqual(result["evidence"], ["Build business operations"])
        self.assertEqual(captured["model"], "gpt-6-luna")
        self.assertEqual(captured["response_format"]["type"], "json_schema")
        self.assertEqual(captured["reasoning_effort"], "none")
        ai_classifier.clear_classifier_cache()
