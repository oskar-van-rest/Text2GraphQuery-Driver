# impl/text2graph_system/prompt.py
from .base_system import BaseLLMSystem
from .templates import (
    ZERO_SHOT_SYSTEM_TMPL, FEW_SHOT_SYSTEM_TMPL,
    CYPHER_EXAMPLES, GQL_EXAMPLES, SQL_EXAMPLES
)

# ======================== Zero-Shot ========================

class CypherZeroShotSystem(BaseLLMSystem):
    def _get_messages(self, question, knowledge):
        specific_knowledge = knowledge if knowledge else "No specific external knowledge provided."
        system_content = ZERO_SHOT_SYSTEM_TMPL.format(
            language_desc="graph query languages, specifically openCypher",
            language_name="openCypher",
            schema_text=self.schema_text,
            knowledge=specific_knowledge
        )
        return [{"role": "system", "content": system_content}, {"role": "user", "content": question.strip()}]

class GQLZeroShotSystem(BaseLLMSystem):
    def _get_messages(self, question, knowledge):
        specific_knowledge = knowledge if knowledge else "No specific external knowledge provided."
        system_content = ZERO_SHOT_SYSTEM_TMPL.format(
            language_desc="graph query languages, specifically ISO GQL (ISO/IEC 39075)",
            language_name="ISO GQL",
            schema_text=self.schema_text,
            knowledge=specific_knowledge
        )
        return [{"role": "system", "content": system_content}, {"role": "user", "content": question.strip()}]

class SQLZeroShotSystem(BaseLLMSystem):
    def _get_messages(self, question, knowledge):
        specific_knowledge = knowledge if knowledge else "No specific external knowledge provided."
        system_content = ZERO_SHOT_SYSTEM_TMPL.format(
            language_desc="relational query languages, specifically SQL",
            language_name="SQL",
            schema_text=self.schema_text,
            knowledge=specific_knowledge
        )
        return [{"role": "system", "content": system_content}, {"role": "user", "content": question.strip()}]

# ======================== Few-Shot ========================

class CypherFewShotSystem(BaseLLMSystem):
    def _get_messages(self, question, knowledge):
        specific_knowledge = knowledge if knowledge else "No specific external knowledge provided."
        system_content = FEW_SHOT_SYSTEM_TMPL.format(
            language_desc="graph query languages, specifically openCypher",
            language_name="openCypher",
            schema_text=self.schema_text,
            knowledge=specific_knowledge,
            examples=CYPHER_EXAMPLES
        )
        return [{"role": "system", "content": system_content}, {"role": "user", "content": question.strip()}]

class GQLFewShotSystem(BaseLLMSystem):
    def _get_messages(self, question, knowledge):
        specific_knowledge = knowledge if knowledge else "No specific external knowledge provided."
        system_content = FEW_SHOT_SYSTEM_TMPL.format(
            language_desc="graph query languages, specifically ISO GQL (ISO/IEC 39075)",
            language_name="ISO GQL",
            schema_text=self.schema_text,
            knowledge=specific_knowledge,
            examples=GQL_EXAMPLES
        )
        return [{"role": "system", "content": system_content}, {"role": "user", "content": question.strip()}]

class SQLFewShotSystem(BaseLLMSystem):
    def _get_messages(self, question, knowledge):
        specific_knowledge = knowledge if knowledge else "No specific external knowledge provided."
        system_content = FEW_SHOT_SYSTEM_TMPL.format(
            language_desc="relational query languages, specifically SQL",
            language_name="SQL",
            schema_text=self.schema_text,
            knowledge=specific_knowledge,
            examples=SQL_EXAMPLES
        )
        return [{"role": "system", "content": system_content}, {"role": "user", "content": question.strip()}]