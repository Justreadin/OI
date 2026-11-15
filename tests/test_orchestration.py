import unittest
from types import SimpleNamespace
from app.orchestration import infer_stage, field_requirements, evidence_audit

class OrchestrationTests(unittest.TestCase):
    def test_detects_experience_stage_and_safe_next_control(self):
        result=infer_stage("Application","https://jobs.example.com",
            [{"label":"Work Experience"}],[{"text":"Continue"},{"text":"Submit application"}])
        self.assertEqual(result["stage"],"experience")
        self.assertEqual(len(result["next_step_controls"]),1)
        self.assertEqual(len(result["final_submission_controls"]),1)

    def test_detects_submission_as_human_gate(self):
        result=infer_stage("Review application","https://jobs.example.com",[],
            [{"text":"Submit application"}])
        self.assertEqual(result["stage"],"submission")
        self.assertTrue(result["human_action_required"])

    def test_required_fields_only(self):
        result=field_requirements([
            {"label":"Email","required":True},
            {"label":"Optional","required":False},
            {"label":"Hidden","required":True,"type":"hidden"}])
        self.assertEqual([x["label"] for x in result],["Email"])

    def test_audit_blocks_missing_core_documents(self):
        app=SimpleNamespace(cv_text="",cover_letter="")
        job=SimpleNamespace(title="Analyst",company="Example")
        result=evidence_audit(job,app,[])
        self.assertFalse(result["ready_for_human_review"])
        self.assertEqual(len(result["blockers"]),2)

if __name__=="__main__": unittest.main()
