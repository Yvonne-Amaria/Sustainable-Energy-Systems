import os 
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import random


def page_ideal_society():
    st.header("Build Your Ideal Society 🎮")
    st.caption(
        "Gamified sandbox: design an ideal community, choose its buildings, energy systems, "
        "and habits — then see how sustainable and resilient your design is."
    )

    # Track high score in session
    if "ideal_society_high_score" not in st.session_state:
        st.session_state["ideal_society_high_score"] = 0.0

    # ---------------- Hero / Images ----------------
    col_img, col_title = st.columns([1, 2])
    with col_img:
        try:
            st.image(
                "assets/ideal_society_hero.jpg",
                caption="Your future society",
                width="stretch",
            )
        except Exception:
            st.write("🔧 Add an image at `assets/ideal_society_hero.jpg` for a custom hero graphic.")

    with col_title:
        society_name = st.text_input(
            "Name your society",
            value="Solaria",
            key="ideal_society_name",
        )
        template = st.selectbox(
            "Choose a starting template",
            [
                "🌱 Eco-Village",
                "🏙️ Solar City",
                "🏝️ Off-Grid Island",
                "🎓 University Town",
                "🚆 Transit-Centered Metro",
            ],
            key="ideal_society_template",
        )
        climate = st.selectbox(
            "Climate region",
            [
                "Cold & cloudy",
                "Temperate",
                "Hot & sunny",
                "Hot & humid",
                "Dry & sunny (desert-like)",
            ],
            key="ideal_society_climate",
        )

        # Little flavor text based on template
        if template == "🌱 Eco-Village":
            st.info("Low-rise, community-focused design with lots of gardens and shared spaces.")
        elif template == "🏙️ Solar City":
            st.info("High-density skyline with solar roofs and transit corridors everywhere.")
        elif template == "🏝️ Off-Grid Island":
            st.info("Microgrids, storage, and resource limits make resilience extra important.")
        elif template == "🎓 University Town":
            st.info("Students, labs, and campus buildings make it a perfect living lab for sustainability.")
        elif template == "🚆 Transit-Centered Metro":
            st.info("Transit hubs, dense corridors, and walkable neighborhoods are the backbone.")

    st.markdown("---")

    # ---------------- Step 0: Random challenge (for fun) ----------------
    with st.expander("🎲 Add a design challenge"):
        challenges = [
            "Your population doubles in 15 years. Can your energy system keep emissions low?",
            "A heatwave hits for 10 days straight. Does your cooling strategy protect everyone?",
            "A major storm cuts one transmission line. How resilient is your local generation?",
            "Food imports become expensive. How much local food can you produce?",
            "A carbon price is introduced. High-emitting options get more expensive overnight.",
        ]
        if st.button("Generate a challenge", key="ideal_society_challenge_btn"):
            st.session_state["ideal_society_challenge"] = random.choice(challenges)

        if "ideal_society_challenge" in st.session_state:
            st.warning(f"Challenge: {st.session_state['ideal_society_challenge']}")

    # ---------------- Step 1: Society basics ----------------
    st.subheader("Step 1 – Society Basics")

    c1, c2, c3 = st.columns(3)
    with c1:
        population = st.slider(
            "Population 👥",
            1_000,
            5_000_000,
            100_000,
            step=1_000,
            key="ideal_society_population",
        )
    with c2:
        density = st.slider(
            "Urban density (people per km²) 🏙️",
            200,
            25_000,
            4_000,
            key="ideal_society_density",
        )
    with c3:
        transit_share = st.slider(
            "Trips by transit / walking / biking (%) 🚶‍♀️🚲🚆",
            0,
            100,
            40,
            key="ideal_society_transit_share",
        )

    st.caption(
        "Higher sustainable mode share (walking, biking, transit) reduces transport emissions and improves health."
    )

    # ---------------- Step 2: Land use & buildings ----------------
    st.subheader("Step 2 – Land Use & Buildings")

    col_land1, col_land2 = st.columns(2)
    with col_land1:
        res_share = st.slider("Residential land (%) 🏠", 0, 100, 40, key="ideal_society_res_share")
        com_share = st.slider("Commercial & services land (%) 🏢", 0, 100, 25, key="ideal_society_com_share")
        ind_share = st.slider("Industry & logistics land (%) 🏭", 0, 100, 15, key="ideal_society_ind_share")
        ag_share = st.slider("Urban agriculture / parks (%) 🌳", 0, 100, 20, key="ideal_society_ag_share")
        total_land = res_share + com_share + ind_share + ag_share
        st.progress(min(total_land / 100, 1.0))
        st.caption(f"Total allocation: **{total_land}%** (target ≈ 100%)")

    with col_land2:
        st.markdown("**Building efficiency features**")
        passive = st.checkbox(
            "Passive house / super-insulated buildings",
            True,
            key="ideal_society_passive",
        )
        heat_pumps = st.checkbox(
            "Heat pumps for space heating & cooling",
            True,
            key="ideal_society_heat_pumps",
        )
        led = st.checkbox(
            "LED lighting everywhere",
            True,
            key="ideal_society_led",
        )
        smart_controls = st.checkbox(
            "Smart controls & building automation",
            True,
            key="ideal_society_smart_controls",
        )
        green_roofs = st.checkbox(
            "Green roofs & high-reflectance surfaces",
            False,
            key="ideal_society_green_roofs",
        )

    # Building-efficiency score
    efficiency_score = 0
    if passive:
        efficiency_score += 30
    if heat_pumps:
        efficiency_score += 25
    if led:
        efficiency_score += 15
    if smart_controls:
        efficiency_score += 15
    if green_roofs:
        efficiency_score += 15
    efficiency_score = min(efficiency_score, 100)

    st.markdown("---")

    # ---------------- Step 3: Energy systems ----------------
    st.subheader("Step 3 – Energy Systems")

    col_energy1, col_energy2 = st.columns([2, 1])
    with col_energy1:
        st.markdown("**Electricity & heat sources**")
        energy_options = st.multiselect(
            "Select all that apply",
            [
                "Rooftop solar PV",
                "Utility-scale solar PV",
                "Onshore wind",
                "Offshore wind",
                "Hydropower",
                "Geothermal electricity",
                "Geothermal heat pumps",
                "Biomass CHP",
                "District heating/cooling",
                "Nuclear (advanced reactors)",
                "Fossil gas with CCS",
            ],
            default=[
                "Rooftop solar PV",
                "Utility-scale solar PV",
                "Onshore wind",
                "Geothermal heat pumps",
                "District heating/cooling",
            ],
            key="ideal_society_energy_options",
        )

        renewables_share = st.slider(
            "Share of electricity from renewables (%) ☀️💨",
            0,
            100,
            85,
            key="ideal_society_renewables_share",
        )
        storage_hours = st.slider(
            "Average storage duration (hours of load) 🔋",
            0.0,
            48.0,
            6.0,
            key="ideal_society_storage_hours",
        )
        demand_response = st.checkbox(
            "Demand response / flexible loads",
            True,
            key="ideal_society_demand_response",
        )

    with col_energy2:
        st.markdown("**Transport & vehicles**")
        ev_share = st.slider(
            "Share of vehicles that are EVs (%) 🚗⚡",
            0,
            100,
            70,
            key="ideal_society_ev_share",
        )
        shared_mobility = st.checkbox(
            "Strong shared mobility (car-share, bike-share)",
            True,
            key="ideal_society_shared_mobility",
        )
        freight_elec = st.checkbox(
            "Electrified freight & logistics",
            False,
            key="ideal_society_freight_elec",
        )

    # Electricity mix visual
    fossil_share = max(0, 100 - renewables_share)
    mix = {"Renewables": renewables_share, "Fossil/Other": fossil_share}
    df_mix = pd.DataFrame({"Source": list(mix.keys()), "Share (%)": list(mix.values())})
    fig_mix = px.pie(
        df_mix,
        names="Source",
        values="Share (%)",
        title="Electricity Mix",
        hole=0.4,
    )
    fig_mix.update_traces(textinfo="percent+label", pull=[0.05, 0])
    st.plotly_chart(fig_mix, width="stretch")

    st.markdown("---")

    # ---------------- Step 4: Lifestyle & circularity ----------------
    st.subheader("Step 4 – Lifestyle & Circularity")

    col_life1, col_life2 = st.columns(2)
    with col_life1:
        reuse_rate = st.slider(
            "Material reuse / recycling rate (%) ♻️",
            0,
            100,
            60,
            key="ideal_society_reuse_rate",
        )
        local_food = st.slider(
            "Food sourced locally / regionally (%) 🥕",
            0,
            100,
            40,
            key="ideal_society_local_food",
        )
        building_reuse = st.checkbox(
            "Adaptive reuse (keep/reuse older buildings where possible)",
            True,
            key="ideal_society_building_reuse",
        )
    with col_life2:
        equity_focus = st.checkbox(
            "Strong equity & access policies (affordable mobility, housing, energy)",
            True,
            key="ideal_society_equity_focus",
        )
        nature_corridors = st.checkbox(
            "Nature corridors & biodiversity protection",
            True,
            key="ideal_society_nature_corridors",
        )
        education_programs = st.checkbox(
            "Education programs on sustainability & climate",
            True,
            key="ideal_society_education_programs",
        )

    circularity_score = reuse_rate * 0.3 + local_food * 0.2
    if building_reuse:
        circularity_score += 15
    if nature_corridors:
        circularity_score += 10
    circularity_score = min(100, circularity_score)

    # ---------------- Scoring logic ----------------
    st.markdown("---")
    st.subheader(f"Results – How does **{society_name}** perform?")

    # Transport score (0–100)
    transport_score = 0.4 * transit_share + 0.4 * ev_share
    if shared_mobility:
        transport_score += 10
    if freight_elec:
        transport_score += 10
    transport_score = min(100, transport_score)

    # Energy score (0–100)
    energy_score = renewables_share
    if storage_hours >= 4:
        energy_score += 10
    if demand_response:
        energy_score += 5
    energy_score = min(100, energy_score)

    # Composite sustainability score
    sustainability_score = (
        0.3 * energy_score
        + 0.25 * transport_score
        + 0.25 * efficiency_score
        + 0.2 * circularity_score
    )

    # Resilience score (very rough)
    resilience_score = (
        0.4 * storage_hours / 24.0 * 100
        + 0.3 * (100 if nature_corridors else 0)
        + 0.3 * (100 if demand_response else 0)
    )
    resilience_score = max(0, min(100, resilience_score))

    # Emissions estimate (tonnes CO2 per person per year, crude)
    baseline = 5.0
    reduction = 0.02 * energy_score + 0.015 * transport_score + 0.01 * efficiency_score
    per_capita_emissions = max(0.3, baseline - reduction / 100 * baseline)

    # -------- Animated-style gauges for main scores --------
    gcol1, gcol2 = st.columns(2)

    with gcol1:
        fig_sus = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=sustainability_score,
                title={"text": f"{society_name}: Sustainability score"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"thickness": 0.3},
                    "steps": [
                        {"range": [0, 40], "color": "#ffb3b3"},
                        {"range": [40, 70], "color": "#ffe9b3"},
                        {"range": [70, 100], "color": "#b3ffd6"},
                    ],
                },
            )
        )
        st.plotly_chart(fig_sus, width="stretch")

    with gcol2:
        fig_res = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=resilience_score,
                title={"text": f"{society_name}: Resilience score"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"thickness": 0.3},
                    "steps": [
                        {"range": [0, 40], "color": "#d6e4ff"},
                        {"range": [40, 70], "color": "#b3e6ff"},
                        {"range": [70, 100], "color": "#b3ffd9"},
                    ],
                },
            )
        )
        st.plotly_chart(fig_res, width="stretch")

    st.metric("Per-capita emissions", f"{per_capita_emissions:.2f} tCO₂/person·yr")

    # -------- Sub-score bar chart for more “game” feedback --------
    st.markdown("#### Where does your society shine?")

    subs_df = pd.DataFrame(
        {
            "Category": ["Energy", "Transport", "Buildings", "Circularity"],
            "Score": [energy_score, transport_score, efficiency_score, circularity_score],
        }
    )
    fig_subs = px.bar(
        subs_df,
        x="Category",
        y="Score",
        range_y=[0, 100],
        text="Score",
        title=f"{society_name}'s strengths",
    )
    fig_subs.update_traces(texttemplate="%{text:.0f}", textposition="outside")
    st.plotly_chart(fig_subs, width="stretch")

    # Highlight the weakest area with a simple suggestion
    weak_category = subs_df.loc[subs_df["Score"].idxmin(), "Category"]
    if weak_category == "Energy":
        tip = "boost renewables share, add storage, or reduce overall demand."
    elif weak_category == "Transport":
        tip = "increase transit/walk/bike share and grow EV adoption."
    elif weak_category == "Buildings":
        tip = "add more passive design, heat pumps, and smart controls."
    else:  # Circularity
        tip = "improve recycling, reuse, and local food systems."

    st.markdown(
        f"👉 To level up **{society_name}**, focus on **{weak_category}** — for example, {tip}"
    )

    # -------- High score + vibe text --------
    previous_best = st.session_state["ideal_society_high_score"]
    if sustainability_score > previous_best:
        st.session_state["ideal_society_high_score"] = sustainability_score
        st.success(f"🎉 New high score for {society_name}: {sustainability_score:.0f} / 100")
        st.balloons()
    else:
        st.caption(
            f"Your best sustainability score so far: **{previous_best:.0f} / 100**. "
            "Try tweaking land use and energy for a new record!"
        )

    # Vibe description based on scores
    def _first_existing(paths):
        """Return the first path that exists, or the first path if none exist."""
        for p in paths:
            if os.path.exists(p):
                return p
        return paths[0]

    if sustainability_score >= 90:
        vibe = "🏆 Net-zero trailblazer"
        desc = (
            f"{society_name} is on track for climate stability with strong social and environmental co-benefits."
        )
        # Try PNG first, then JPG
        vibe_image_path = _first_existing(
            ["assets/society_excellent.png", "assets/society_excellent.jpg"]
        )
    elif sustainability_score >= 70:
        vibe = "✨ Strong performer"
        desc = (
            f"{society_name} is close to a climate-stable design. A few more pushes on transport and efficiency "
            "could get you there."
        )
        vibe_image_path = _first_existing(
            ["assets/society_strong.png", "assets/society_strong.jpg"]
        )
    elif sustainability_score >= 50:
        vibe = "🛠 In transition"
        desc = (
            f"{society_name} shows good progress, but fossil energy and car dependence are still high. Keep iterating!"
        )
        vibe_image_path = _first_existing(
            ["assets/society_transition.png", "assets/society_transition.jpg"]
        )
    else:
        vibe = "⚠️ High risk"
        desc = (
            f"{society_name} faces high emissions and lower resilience. Use this as a starting point to experiment."
        )
        vibe_image_path = _first_existing(
            ["assets/society_horrible.png", "assets/society_horrible.jpg"]
        )

    st.markdown(f"### Society vibe for **{society_name}**: {vibe}")
    st.write(desc)

    # -------- Visual vibe images (your art goes here) --------
    st.markdown("#### Visual for this society")
    if os.path.exists(vibe_image_path):
        st.image(vibe_image_path, width='stretch')
    else:
        st.caption(
            "Could not find an image file for this vibe.\n\n"
            "Make sure one of these exists in your project:\n"
            "- `assets/society_horrible.png` or `.jpg`\n"
            "- `assets/society_transition.png` or `.jpg`\n"
            "- `assets/society_strong.png` or `.jpg`\n"
            "- `assets/society_excellent.png` or `.jpg`\n"
        )


    # ---------------- Explanation tab ----------------
    with st.expander("How were these scores calculated? (educational view)"):
        st.markdown(
            """
            **High-level idea (not a real planning model):**

            - We compute separate scores for:
              - Energy systems (renewables %, storage, demand response)
              - Transport (transit/walk/bike share, EV share, freight electrification)
              - Building efficiency (passive design, heat pumps, LEDs, controls)
              - Circularity (reuse, recycling, local food, land use)
            - The overall *sustainability score* is a weighted average of these components.
            - The *per-capita emissions* start from a generic baseline and are reduced when
              your scores are high.

            This is meant as an educational game to think through tradeoffs, not an engineering design tool.
            """
        )

    # ---------------- Reset button (for playing again) ----------------
    st.markdown("---")
    if st.button("Reset choices and design a new society"):
        # Clear game-specific session keys but keep high score
        for key in list(st.session_state.keys()):
            if key.startswith("ideal_society_") and key != "ideal_society_high_score":
                st.session_state.pop(key, None)

        # Force a fresh rerun so all widgets go back to defaults immediately
        if hasattr(st, "rerun"):
            st.rerun()
        elif hasattr(st, "experimental_rerun"):
            st.experimental_rerun()
        else:
            st.info("Please manually rerun the app to see the reset take effect.")
