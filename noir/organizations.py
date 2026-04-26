import sqlite3

SEEDED_ORGANIZATIONS = [
    {
        "name": "New Orleans Police Department",
        "type": "government",
        "description": (
            "The NOPD operates as much as a political instrument as a law enforcement agency. "
            "Officers owe their jobs to ward bosses and political patrons. Brutality toward Black "
            "residents is systematic and rarely questioned. The department is predominantly white, "
            "Catholic, and deeply entangled with the city's criminal underworld. Members are expected "
            "to look after their own. Outsiders — including reform-minded detectives — are viewed "
            "with suspicion."
        ),
        "is_hierarchical": 1,
        "influence": 7,
    },
    {
        "name": "Orleans Parish Government",
        "type": "government",
        "description": (
            "The governing body of Orleans Parish, encompassing the City Council, the Mayor's office, "
            "and the various administrative departments. Dominated by the Long machine and its allies. "
            "Membership confers access to city contracts, patronage jobs, and judicial appointments. "
            "Functionally whites-only at any level of consequence."
        ),
        "is_hierarchical": 1,
        "influence": 8,
    },
    {
        "name": "Louisiana State Government",
        "type": "government",
        "description": (
            "The state apparatus under Governor Long's successors. Controls roads, schools, patronage, "
            "and the oil tax regime. More powerful than the city government on most matters of "
            "consequence. Operatives in Noirleans report upward to Baton Rouge."
        ),
        "is_hierarchical": 1,
        "influence": 9,
    },
    {
        "name": "Rossi Crime Family",
        "type": "crime_family",
        "description": (
            "Italian-American organized crime with roots in Sicily. Controls French Quarter gambling, "
            "loan sharking, and labor rackets in the shipping industry. Hierarchical and insular — "
            "loyalty to the family supersedes everything. Predominantly Italian or Sicilian. "
            "Maintains a working relationship with certain NOPD officials."
        ),
        "is_hierarchical": 1,
        "influence": 8,
    },
    {
        "name": "Castellano Crime Family",
        "type": "crime_family",
        "description": (
            "Rival Italian-American family with roots in the Marigny. Controls prostitution and "
            "narcotics in the Back of Town. Currently in uneasy peace with the Rossis following "
            "a territorial settlement in 1932. Predominantly Italian. More willing than the Rossis "
            "to work with non-Italian associates."
        ),
        "is_hierarchical": 1,
        "influence": 6,
    },
    {
        "name": "International Longshoremen's Association Local 231",
        "type": "union",
        "description": (
            "The dockworkers union covering the Port of New Orleans. Historically integrated — "
            "Black and white workers share membership and leadership, a rare arrangement in the South "
            "that has made the local a target of political pressure. Connected to the crime families "
            "through the port labor rackets. Membership is overwhelmingly working-class."
        ),
        "is_hierarchical": 1,
        "influence": 5,
    },
    {
        "name": "Archdiocese of New Orleans",
        "type": "church",
        "description": (
            "The Roman Catholic Church's administrative body for southern Louisiana. One of the "
            "oldest and most powerful Catholic institutions in North America. Membership encompasses "
            "clergy, lay leaders, and associated religious organizations. Predominantly white but with "
            "a significant Creole Catholic community. Has historically maintained separate parishes "
            "for Black Catholics."
        ),
        "is_hierarchical": 1,
        "influence": 6,
    },
    {
        "name": "New Orleans Athletic Club",
        "type": "fraternal",
        "description": (
            "The city's premier social club for white men of wealth and standing. Membership is "
            "by invitation only and requires sponsorship from two existing members. Excludes women, "
            "Black residents, Jews, and most new-money Catholics. The real business of the city — "
            "contracts, appointments, prosecutorial decisions — is often arranged here over lunch."
        ),
        "is_hierarchical": 0,
        "influence": 7,
    },
    {
        "name": "Knights of Columbus",
        "type": "fraternal",
        "description": (
            "Catholic fraternal organization with strong presence in Noirleans' Irish and Italian "
            "communities. Membership open to practicing Catholic men. Provides mutual aid, "
            "political solidarity, and social networks for its members. A significant pipeline "
            "into city government and the NOPD for Catholic men without old-money connections."
        ),
        "is_hierarchical": 0,
        "influence": 4,
    },
    {
        "name": "Treme Social Aid and Pleasure Club",
        "type": "fraternal",
        "description": (
            "One of the oldest Black social clubs in Noirleans, rooted in the Treme neighborhood. "
            "Provides mutual aid, funeral support, and community solidarity. Membership is Black "
            "and working-class to middle-class. Has informal connections to Black-owned businesses "
            "and the city's underground economy. Operates in parallel to white civic institutions "
            "that exclude its members."
        ),
        "is_hierarchical": 0,
        "influence": 3,
    },
    {
        "name": "Colored Longshoremen's Association",
        "type": "union",
        "description": (
            "The separate Black dockworkers organization that operates alongside ILA Local 231. "
            "Despite formal integration of the port locals, in practice Black workers are often "
            "channeled through this organization. Has its own leadership and mutual aid structure. "
            "Membership is Black and working-class."
        ),
        "is_hierarchical": 1,
        "influence": 3,
    },
    {
        "name": "Noirleans Bar Association",
        "type": "professional",
        "description": (
            "The professional organization for attorneys practicing in Orleans Parish. Membership "
            "is effectively required for courthouse work. Overwhelmingly white and male. Functions "
            "as a social and political network as much as a professional body. Maintains close ties "
            "to the judiciary."
        ),
        "is_hierarchical": 0,
        "influence": 5,
    },
    {
        "name": "Orleans Parish Judiciary",
        "type": "government",
        "description": (
            "The judges of the Orleans Parish Criminal and Civil District Courts. Appointments and "
            "elections to the bench run through the same political networks that control the rest of "
            "city government — the Long machine, the ward bosses, and the Bar Association all have "
            "fingers in the process. Judges enjoy significant personal discretion over their courtrooms "
            "and rarely face meaningful accountability. Membership is exclusively white, male, and "
            "Catholic or at least Catholic-adjacent."
        ),
        "is_hierarchical": 1,
        "influence": 7,
    },
    {
        "name": "Shorties",
        "type": "political",
        "description": (
            "Supporters of the Short machine — the populist political network built by Governor Short "
            "and maintained by his successors. Provides patronage jobs, infrastructure contracts, and "
            "political protection to its members. Deliberately race-neutral in its public programs, "
            "which is both its strength and the source of its enemies. Membership spans class and "
            "neighborhood lines in a way unusual for New Orleans politics."
        ),
        "is_hierarchical": 1,
        "influence": 8,
    },
    {
        "name": "Tallboys",
        "type": "political",
        "description": (
            "The anti-Short coalition — a loose alliance of old-guard political families, business "
            "interests, and reactionary elements who feel the Short machine stole what was rightfully "
            "theirs. The coalition includes former KKK members who lost power during the Short years "
            "and have not forgotten it. Unified by resentment more than ideology. Predominantly white, "
            "Catholic, and drawn from families with pre-Short political ties."
        ),
        "is_hierarchical": 0,
        "influence": 6,
    },
    {
        "name": "Chamber of Commerce",
        "type": "political",
        "description": (
            "The organized voice of New Orleans business interests. Aggressively anti-union, "
            "hostile to labor organizing, and focused on keeping wages low and regulations light. "
            "Corrupt in the way of influence peddling and favorable contracts rather than street-level "
            "graft. Members are merchants, manufacturers, and property owners. Membership is exclusively "
            "white."
        ),
        "is_hierarchical": 1,
        "influence": 7,
    },
    {
        "name": "NAACP New Orleans Chapter",
        "type": "civic",
        "description": (
            "The New Orleans chapter of the National Association for the Advancement of Colored People. "
            "Focused on legal challenges to segregation, voter suppression, and police brutality. "
            "Operates with limited resources under constant pressure. Membership is Black and includes "
            "professionals, clergy, and community leaders. Works through legal channels where possible; "
            "maintains community networks where it cannot."
        ),
        "is_hierarchical": 1,
        "influence": 5,
    },
    {
        "name": "The Press",
        "type": "press",
        "description": (
            "The loose network of journalists, editors, and publishers working in Noirleans — "
            "primarily the white dailies but including the Black press. The press has the power to "
            "expose and to bury, and everyone in the city knows it. Journalists are poorly paid, "
            "often corrupt, and occasionally brave. Membership is informal — anyone with press "
            "credentials and a story."
        ),
        "is_hierarchical": 0,
        "influence": 5,
    },
    {
        "name": "Treme Pawn & Loan",
        "type": "independent",
        "description": "A pawn and loan shop in the Tremé. Buys and sells without asking questions about provenance.",
        "is_hierarchical": 0,
        "influence": 1,
    },
]


FIXED_LOCATION_ORGS: dict[str, list[str]] = {
    "The Precinct":    ["New Orleans Police Department"],
    "The DA's Office": ["Orleans Parish Government", "Noirleans Bar Association"],
    "The Courthouse":  ["Orleans Parish Judiciary", "Noirleans Bar Association"],
    "City Hall":       ["Orleans Parish Government", "Louisiana State Government"],
    "Sheriff's Office":["New Orleans Police Department", "Orleans Parish Government"],
    "Rossi's":         ["Rossi Crime Family"],
    "The Marigny Room":["Castellano Crime Family"],
    "The Rusty Anchor":["Rossi Crime Family"],
    "City Morgue":     ["New Orleans Police Department"],
}


def seed_organizations(conn: sqlite3.Connection) -> None:
    """Insert seeded organizations and location links if they don't exist yet."""
    for org in SEEDED_ORGANIZATIONS:
        existing = conn.execute(
            "SELECT id FROM organizations WHERE name=?", (org["name"],)
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO organizations (name, type, description, is_hierarchical, is_seeded, influence)
                   VALUES (?, ?, ?, ?, 1, ?)""",
                (org["name"], org["type"], org["description"],
                 org["is_hierarchical"], org["influence"])
            )

    conn.commit()


def seed_location_org_links(conn: sqlite3.Connection) -> None:
    """Link fixed locations to their orgs. Call after fixed locations are created."""
    for loc_name, org_names in FIXED_LOCATION_ORGS.items():
        loc_row = conn.execute("SELECT id FROM locations WHERE name=?", (loc_name,)).fetchone()
        if not loc_row:
            continue
        for org_name in org_names:
            org_row = conn.execute("SELECT id FROM organizations WHERE name=?", (org_name,)).fetchone()
            if not org_row:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO location_organizations (location_id, organization_id)
                   VALUES (?, ?)""",
                (loc_row["id"], org_row["id"])
            )
    conn.commit()
