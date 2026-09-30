# Data Agent prompts

Try these against **NereusFleetAgent** (data source: `NereusFleetOntology`). Keep the simulator running so live values resolve.
Answers from a preview agent can vary – rehearse the ones you plan to show.

## Fleet & live position

- Where is NT Ariadne now and what is the status of her main engine?
- For every vessel, show its type, current speed, navigation status and destination.
- Which vessels are currently laden and which are in ballast?
- Which vessel is diverted and where is it heading?

## Main engines

- Show the main engine maker, model and MCR for every vessel.
- Which vessels currently have a main engine fault, and what is the fault type?
- Rank the vessels by current fuel consumption in tonnes per day.
- What is the current turbocharger vibration on NT Kallisto?

## Cargo & safety

- Which cargo tanks currently have inert-gas O2 above 6 %?
- List the cargo tanks of NT Nefeli with capacity, coating and current O2.

## Voyages & commercial

- List the current laden voyages with vessel, cargo grade, quantity, load port, discharge port and charterer.
- Which voyages are in EU ETS scope at 100 %?
- Which charterer has the most voyages, and what is its credit rating?

## Maintenance

- List all Critical or High priority maintenance orders with the vessel and superintendent.
- Which open maintenance orders are scheduled at the Perama Ship Repair Zone?
- What is the total cost of completed maintenance orders per vessel in 2026?

## Emissions & compliance

- Which vessels had a CII rating of D in 2026?
- Show CO2 and EUA cost per vessel for 2026-08.
- Which vessel had the highest total CO2 between 2026-01 and 2026-08?
