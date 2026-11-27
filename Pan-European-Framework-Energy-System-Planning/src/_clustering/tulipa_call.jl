using TulipaClustering
using TulipaIO
using DataFrames
using DuckDB
using Distances
using CSV

println("WARNING: Check whether there are extreme periods from the loop with the operational assessments")

# --- Temporal resolution -----------------------------------------------------
# EU reference case: 5 representatives x 24 timesteps (5 representative days).
# IC1 is reduced further for FEASIBILITY TESTING ONLY. The question right now is
# whether the model can solve at all, not whether the answer is defensible.
#
# number_of_timesteps is the period DURATION in hours. Below 24 the periods are
# no longer whole days, which degrades intra-day storage cycling and anything
# depending on a diurnal profile (solar above all). A 4-hour period cannot
# represent a day/night cycle; a 1-hour period is a SINGLE timestep, so there is
# no intra-period dynamics whatsoever and storage is degenerate by construction.
#
# This was only tunable after clustering_output.py stopped hardcoding 24 for the
# block boundaries and the representative_blocks_by_period map; it now derives
# the duration from the weights file instead.
#
# RESTORE to number_of_timesteps = 24 (and ideally >= 5 representatives)
# before any result is reported, compared against the EU case, or published.
#
# 2026-09-27: raised to ONE REPRESENTATIVE DAY (1 x 24 h). Going 1 h -> 24 h is
# what changes the physics: it restores the diurnal cycle, without which storage
# is degenerate by construction (a 1-hour period is a single timestep, so there
# is no intra-period dynamics to arbitrage and storage investment was pinned at
# exactly 0.00). Adding representatives instead would only add a second weather
# pattern at double the cost. Still below the EU case's 5 x 24 h.
#
# 2026-09-28: raised to THREE REPRESENTATIVE DAYS (3 x 24 h).
#
# One representative day was not enough, and the reason is specific: the single
# medoid landed on 12 JANUARY, which is midwinter and not representative of the
# year at all. Measured against the wy2009 profiles:
#
#     technology        annual mean    12 Jan
#     solar-PV  BEC1       0.1346      0.0512
#     solar-PV  NLC5       0.1429      0.0433
#     wind-on   BEC1       0.3045      0.9255
#     wind-on   NLC5       0.4290      0.9493
#
# Solar was shown at ~1/3 of its annual average and wind at 2-3x its annual
# average, and that single day was then weighted x365. The model consequently
# built +32.8 units of onshore wind and ZERO solar PV, and zero batteries (a
# near-constant 0.95 wind day offers nothing to arbitrage). Those are artefacts
# of the sample, not results.
#
# Three medoids should span a wider set of weather patterns and bring the
# blended day closer to an annual average. Cost is ~3x the operational
# timesteps (75 -> ~219 in the tiny model), which is affordable because the
# operations_y* blocks stay coarsened at 365D - this does NOT reintroduce the
# 8760-hour build.
#
# Still below the EU case's 5 x 24 h.
# 2026-09-28 (later): reduced to TWO representative days, but PINNED rather than
# clustered, via results/initial_representative_periods_wy2009.csv.
#
# The 3-representative run (medoids 12, 49, 231) produced a 3,043,463-column LP
# that hit the 6 h time limit with primal: NO_SOLUTION and an EMPTY results DB.
# Extrapolating from atmfix (893,361 cols, 675,067 iterations, optimal in 38
# min), 3 reps needs an estimated 9-25 h. Two reps is ~2x atmfix rather than
# ~3.4x, which should land in the 1.5-3 h range we have direct evidence for.
#
# Dropping to 2 by re-clustering would NOT guarantee a summer day - k=2 could
# easily return two winter/shoulder medoids and reproduce exactly the bug we are
# trying to fix. So the days are pinned instead: 12 (midwinter, the original
# medoid) and 231 (19 Aug, the summer day that k=3 found). The seed file is
# consumed by the `isfile(initial_path)` branch below, which also DERIVES the
# representative count from the file, so number_of_representatives is overridden
# when that file is present.
#
# The pinned pair BRACKETS the annual mean on every weather-driven profile,
# which a single midwinter day structurally cannot:
#
#     profile         annual    12 Jan    19 Aug
#     solar           0.1433    0.0624    0.2776
#     wind            0.3969    0.9778    0.2045
#     cool            0.0917    0.0000    0.4309
#     DHW_or_space    0.3469    0.5169    0.2439
#
# Note that cooling demand is EXACTLY ZERO on 12 January, so the 1-rep model had
# no cooling load anywhere in the horizon.
#
# To go back to unpinned clustering, delete
# results/initial_representative_periods_wy2009.csv and set the count below.
# Regenerate the seed with tools/make_cluster_seed.py.
#
# Still below the EU case's 5 x 24 h.

# 2026-09-29: SUMMER-ONLY RUN. One representative day, PINNED to day 231
# (19 August), via results/initial_representative_periods_wy2009.csv.
#
# This is a deliberate CONTRAST to the original 1-rep run, which used 12 January
# and biased the model hard towards wind. A single summer day biases the other
# way. Neither is a defensible standalone result; the PAIR is what is
# informative, because it brackets the annual mean:
#
#     profile         annual    12 Jan    19 Aug
#     solar           0.1433    0.0624    0.2776
#     wind            0.3969    0.9778    0.2045
#     cool            0.0917    0.0000    0.4309
#     DHW_or_space    0.3469    0.5169    0.2439
#
# Note cooling demand is EXACTLY ZERO on 12 January, so the winter run had no
# cooling load anywhere in the horizon.
#
# The previous "2 representative day" run (12 Jan + 19 Aug) was INVALID: a stale
# results/representative_periods.csv made clustering_output.py stamp the blocks
# onto 12 Jan and 18 FEB, so it silently solved as a two-WINTER-day model. See
# the comment in clustering_output.py. That is now a hard error.
#
# number_of_representatives is OVERRIDDEN by the seed file whenever it exists;
# the value below only applies on the unseeded path.

number_of_representatives = 7   # overridden by the seed file when it exists.
number_of_timesteps = 24   # one full day, restoring the diurnal cycle.

function get_data(input_folder,year)
  dir = joinpath(input_folder, "profiles")
  con = DBInterface.connect(DuckDB.DB)
  TulipaIO.create_tbl(con, joinpath(dir, string("profiles","_",year,".csv")); name = "profiles")
  return DBInterface.execute(con, "SELECT * FROM profiles") |> DataFrame
end

input_folder = joinpath(@__DIR__, "")
rp_df = DataFrame()
for alternative in ["wy2009"]
    println("--------",alternative,"--------")

    println("Importing Data")
    clustering_data = get_data(input_folder,string(alternative))
    println("Splitting Periods")
    split_into_periods!(clustering_data; period_duration = number_of_timesteps)

    initial_path = string("results/initial_representative_periods_",alternative,".csv")
    if isfile(initial_path)
        initial_df = DataFrame(CSV.File(initial_path))
        new_number_of_representatives = length(unique(initial_df.period))
        @info "File Uploaded" initial_path size=size(initial_df)
        println("Finding Representative Periods with Extremes")
        clustering_result = find_representative_periods(
            clustering_data,
            new_number_of_representatives;
            initial_representatives = initial_df,
            drop_incomplete_last_period = false,
            method = :convex_hull, # k_means, k_medoids, convex_hull, convex_hull_with_null, conical_hull
            distance = Euclidean(), #Any distance from Distances.jl e.g., SqEuclidean(), or CosineDist()
            # init = :kmcen,
        )
    else
        @warn "File doest not exist in that directory" initial_path
        println("Finding Representative Periods with no Extremes")
        clustering_result = find_representative_periods(
            clustering_data,
            number_of_representatives;
            drop_incomplete_last_period = false,
            method = :convex_hull, # k_means, k_medoids, convex_hull, convex_hull_with_null, conical_hull
            distance = Euclidean(), #Any distance from Distances.jl e.g., SqEuclidean(), or CosineDist()
            # init = :kmcen,
        )
        println("Saving Representative Periods ",alternative, clustering_result.auxiliary_data.medoids)
        #medoids = clustering_result.auxiliary_data.medoids
        rp_df[!,alternative] = clustering_result.auxiliary_data.medoids
        CSV.write(string("results/representative_periods.csv"),rp_df);
    end

    println("Calculating Weights")
    TulipaClustering.fit_rep_period_weights!(
      clustering_result;
      weight_type = :convex, # :dirac, :convex, :conical_bounded
      niters = 1000,
      learning_rate = 1e-3
    )

    println("Writting Results")
    weights = TulipaClustering.weight_matrix_to_df(clustering_result.weight_matrix)
    CSV.write(string("results/weights","_",alternative,".csv"),weights)
    
end
