# impl/text2graph_system/templates.py

# ======================== Base Templates ========================
ZERO_SHOT_SYSTEM_TMPL = """You are an expert in {language_desc}.
Schema:
{schema_text}

Domain knowledge:
{knowledge}

Task: Convert the user's natural language question into a {language_name} query.
Output: Return only the query string."""

FEW_SHOT_SYSTEM_TMPL = """You are an expert in {language_desc}.
The database schema is as follows:
{schema_text}

Domain Knowledge:
{knowledge}

Task: Convert the user's natural language question into a {language_name} query.
Output: Return only the query string.

The user's question and corresponding output examples are as follows:

{examples}"""

# ======================== Few-Shot Examples ========================
CYPHER_EXAMPLES = """Example 1
Question: Which characters have a path to "Catelyn-Stark" in the interaction network with a maximum of 3 hops?
Output: MATCH (c:Character)-[:INTERACTS*1..3]->(target:Character {name: 'Catelyn-Stark'}) RETURN DISTINCT c.name

Example 2
Question: How many people have directed more than two movies?
Output: MATCH (p:Person)-[:DIRECTED]->(m:Movie) WITH p, count(m) AS moviesDirected WHERE moviesDirected > 2 RETURN count(p) AS directorsCount

Example 3
Question: List the top 5 movies with the most production companies involved.
Output: MATCH (m:Movie)-[:PRODUCED_BY]->(pc:ProductionCompany) WITH m, COUNT(pc) AS productionCompanyCount ORDER BY productionCompanyCount DESC LIMIT 5 RETURN m.title AS MovieTitle, productionCompanyCount"""

GQL_EXAMPLES = """Example 1
Question: Please list the Asian populations of all the residential areas with the bad alias "URB San Joaquin".
Output: MATCH (t1:zip_data)<-[zip_code:ZIP_CODE]-(t2:avoid) WHERE t2.bad_alias = 'URB San Joaquin' RETURN sum(t1.asian_population)

Example 2
Question: What is the country and state of the city named Dalton?
Output: MATCH (t1:state)<-[t2:country]-(t3:zip_data) WHERE t3.city = 'Dalton' RETURN t2.county

Example 3
Question: How many cities does congressman Pierluisi Pedro represent?
Output: MATCH (t1:zip_data)<-[t2:zip_congress]-(t3:congress) WHERE (t3.first_name = 'Pierluisi' AND t3.last_name = 'Pedro') RETURN count(DISTINCT t1.city)"""

SQL_EXAMPLES = """Example 1
Question: Please list the Asian populations of all the residential areas with the bad alias "URB San Joaquin".
Output: SELECT SUM(T1.asian_population) FROM zip_data AS T1 INNER JOIN avoid AS T2 ON T1.zip_code = T2.zip_code WHERE T2.bad_alias = 'URB San Joaquin'

Example 2
Question: What is the country and state of the city named Dalton?
Output: SELECT T2.county FROM state AS T1 INNER JOIN country AS T2 ON T1.abbreviation = T2.state INNER JOIN zip_data AS T3 ON T2.zip_code = T3.zip_code WHERE T3.city = 'Dalton' GROUP BY T2.county

Example 3
Question: How many cities does congressman Pierluisi Pedro represent?
Output: SELECT COUNT(DISTINCT T1.city) FROM zip_data AS T1 INNER JOIN zip_congress AS T2 ON T1.zip_code = T2.zip_code INNER JOIN congress AS T3 ON T2.district = T3.cognress_rep_id WHERE T3.first_name = 'Pierluisi' AND T3.last_name = 'Pedro'"""