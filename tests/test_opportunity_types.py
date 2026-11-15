import unittest
from app.scoring import classify_opportunity_type

class OpportunityTypeTests(unittest.TestCase):
    def test_internship_titles(self):
        for title in ["Product Management Intern", "Summer Research Internship", "Intern, Growth"]:
            with self.subTest(title=title):
                self.assertEqual(classify_opportunity_type(title), "Internship")

    def test_fellowship_and_programmes(self):
        self.assertEqual(classify_opportunity_type("Venture Fellow"), "Fellowship")
        self.assertEqual(classify_opportunity_type("Graduate Trainee Programme"), "Graduate Programme")
        self.assertEqual(classify_opportunity_type("Early Career Rotational Programme"), "Early-Career Programme")

    def test_does_not_mistake_junior_role_for_internship(self):
        self.assertEqual(classify_opportunity_type("Junior Research Analyst"), "Other")
        self.assertEqual(classify_opportunity_type("Graduate Research Analyst"), "Other")

    def test_employment_type(self):
        self.assertEqual(classify_opportunity_type("Part-time Product Associate"), "Part-Time Employment")
        self.assertEqual(classify_opportunity_type("Full-Time Strategy Associate"), "Full-Time Employment")

if __name__ == "__main__":
    unittest.main()
