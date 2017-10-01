"""Base class for bio-inspired optimizers."""

from concurrent import futures
import datetime
import enum
import os
import sys

from deap import base, creator, tools
import numpy
import matplotlib.pylab as plt

from external_programs.profit import run_profit


def default_build(spec_seq_params):
    specification, sequence, params = spec_seq_params
    model = specification(*params)
    model.pack_new_sequences(sequence)
    return model


def buff_interaction_eval(ampal):
    return ampal.buff_interaction_energy.total_energy


def buff_internal_eval(ampal):
    return ampal.buff_internal_energy.total_energy


def make_rmsd_eval(reference_ampal):
    def rmsd_eval(ampal):
        ca, bb, aa = run_profit(
            ampal.pdb, reference_ampal,
            path1=False, path2=False)
        return bb
    return rmsd_eval


class BaseOptimizer:
    """Abstract base class for the evolutionary optimizers.

    Notes
    -----
    Not intended to be used directly, see the evolutionary
    optimizers for full documentation.
    """

    def __init__(self, specification, build_fn=None, eval_fn=None, **kwargs):
        self.specification = specification
        if sys.platform == 'win32':
            self.mp_disabled = True
            print('Multiprocessing for this module is currently unavailable'
                  'on Windows, only a single process will be used.')
        else:
            self.mp_disabled = False
        self.build_fn = build_fn
        self.eval_fn = eval_fn
        self.population = None
        creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
        self.toolbox = base.Toolbox()
        self.parameter_log = []
        self._cores = 1
        self._evals = 0
        self._model_count = 0
        self._store_params = True

    @classmethod
    def buff_interaction_eval(cls, specification, **kwargs):
        """Creates optimizer with default build and BUFF interaction eval.

        Notes
        -----
        Any keyword arguments will be propagated down to BaseOptimizer.

        Parameters
        ----------
        specification: ampal.assembly.specification
            Any assembly level specification.
        """
        instance = cls(build_fn=default_build,
                       eval_fn=buff_interaction_eval,
                       specification=specification,
                       **kwargs)
        return instance

    @classmethod
    def buff_internal_eval(cls, specification, **kwargs):
        """Creates optimizer with default build and BUFF interaction eval.
        
        Notes
        -----
        Any keyword arguments will be propagated down to BaseOptimizer.

        Parameters
        ----------
        specification: ampal.assembly.specification
            Any assembly level specification.
        """
        instance = cls(build_fn=default_build,
                       eval_fn=buff_internal_eval,
                       specification=specification,
                       **kwargs)
        return instance

    @classmethod
    def rmsd_eval(cls, specification, reference_ampal, **kwargs):
        """Creates optimizer with default build and RMSD eval.
        
        Notes
        -----
        Any keyword arguments will be propagated down to BaseOptimizer.

        RMSD eval is restricted to a single core only, due to restrictions
        on closure pickling.

        Parameters
        ----------
        specification: ampal.assembly.specification
            Any assembly level specification.
        """
        eval_fn = make_rmsd_eval(reference_ampal)
        instance = cls(build_fn=default_build,
                       eval_fn=eval_fn,
                       specification=specification,
                       mp_disabled=True,
                       **kwargs)
        return instance

    def parse_individual(self, individual):
        """Converts a deap individual into a full list of parameters.

        Parameters
        ----------
        individual: deap individual from optimization
            Details vary according to type of optimization, but
            parameters within deap individual are always between -1
            and 1. This function converts them into the values used to
            actually build the model

        Returns
        -------
        fullpars: list
            Full parameter list for model building.
        """
        scaled_ind = []
        for i in range(len(self.value_means)):
            scaled_ind.append(self.value_means[i] + (
                individual[i] * self.value_ranges[i]))
        fullpars = list(self.arrangement)
        for k in range(len(self.variable_parameters)):
            for j in range(len(fullpars)):
                if fullpars[j] == self.variable_parameters[k]:
                    fullpars[j] = scaled_ind[k]
        return fullpars

    def run_opt(self, pop_size, generations, cores=1, plot=False, log=False,
                log_path=None, run_id=None, store_params=True, **kwargs):
        """Runs the optimizer.

        Parameters
        ----------
        pop_size: int
            Size of the population each generation.
        generation: int
            Number of generations in optimisation.
        cores: int, optional
            Number of CPU cores used to run the optimisation.
            If the 'mp_disabled' keyword is passed to the
            optimizer, this will be ignored and one core will
            be used.
        plot: bool, optional
            If true, matplotlib will be used to plot information
            about the minimisation.
        log: bool, optional
            If true, a log file describing the optimisation will
            be created. By default it will be written to the
            current directory and named according to the time the
            minimisation finished. This can be manually specified
            by passing the 'output_path' and 'run_id' keyword
            arguments.
        store_params: bool, optional
            If true, the parameters for each model created during
            the optimisation will be stored. This can be used to
            create funnel data later on.
        """
        # allows us to pass in additional arguments e.g. neighbours
        self._cores = cores
        self._store_params = store_params
        self.parameter_log = []
        self.halloffame = tools.HallOfFame(1)
        self.stats = tools.Statistics(lambda thing: thing.fitness.values)
        self.stats.register("avg", numpy.mean)
        self.stats.register("std", numpy.std)
        self.stats.register("min", numpy.min)
        self.stats.register("max", numpy.max)
        self.logbook = tools.Logbook()
        self.logbook.header = ["gen", "evals"] + self.stats.fields
        start_time = datetime.datetime.now()
        self._initialize_pop(pop_size)
        for g in range(generations):
            self._update_pop(pop_size)
            self.halloffame.update(self.population)
            self.logbook.record(gen=g, evals=self._evals,
                                **self.stats.compile(self.population))
            print(self.logbook.stream)
        end_time = datetime.datetime.now()
        time_taken = end_time - start_time
        print("Evaluated {} models in total in {}".format(
            self._model_count, time_taken))
        print("Best fitness is {0}".format(self.halloffame[0].fitness))
        print("Best parameters are {0}".format(self.parse_individual(
            self.halloffame[0])))
        for i, entry in enumerate(self.halloffame[0]):
            if entry > 0.95:
                print(
                    "Warning! Parameter {0} is at or near maximum allowed "
                    "value\n".format(i + 1))
            elif entry < -0.95:
                print(
                    "Warning! Parameter {0} is at or near minimum allowed "
                    "value\n".format(i + 1))
        if log:
            self.log_results(output_path=output_path, run_id=run_id)
        if plot:
            print('----Minimisation plot:')
            plt.figure(figsize=(5, 5))
            plt.plot(range(len(self.logbook.select('min'))),
                     self.logbook.select('min'))
            plt.xlabel('Iteration', fontsize=20)
            plt.ylabel('Score', fontsize=20)
        return

    def parameters(self, sequence, value_means, value_ranges, arrangement):
        """Relates the individual to be evolved to the full parameter string.

        Parameters
        ----------
        sequence: str
            Full amino acid sequence for specification object to be
            optimized. Must be equal to the number of residues in the
            model.
        value_means: list
            List containing mean values for parameters to be optimized.
        value_ranges: list
            List containing ranges for parameters to be optimized.
            Values must be positive.
        arrangement: list
            Full list of fixed and variable parameters for model
            building. Fixed values are the appropriate value. Values
            to be varied should be listed as 'var0', 'var1' etc,
            and must be in ascending numerical order.
            Variables can be repeated if required.
        """
        self.sequence = sequence
        self.value_means = value_means
        self.value_ranges = value_ranges
        self.arrangement = arrangement
        if any(x <= 0 for x in self.value_ranges):
            raise ValueError("range values must be greater than zero")
        self.variable_parameters = []
        for i in range(len(self.value_means)):
            self.variable_parameters.append(
                "".join(['var', str(i)]))
        if len(set(arrangement).intersection(
                self.variable_parameters)) != len(
                    self.value_means):
            raise ValueError("argument mismatch!")
        if len(self.value_ranges) != len(
                self.value_means):
            raise ValueError("argument mismatch!")
        return

    def assign_fitnesses(self, targets):
        """Assigns fitnesses to parameters.
        
        Notes
        -----
        Uses `self.eval_fn` to evaluate each member of target.
        Parameters
        ---------

        targets
            Parameter values for each member of the population.
        """
        self._evals = len(targets)
        px_parameters = zip([self.specification] * len(targets),
                            [self.sequence] * len(targets),
                            [self.parse_individual(x) for x in targets])
        if (self._cores == 1) or (self.mp_disabled):
            models = map(self.build_fn, px_parameters)
            fitnesses = map(self.eval_fn, models)
        else:
            with futures.ProcessPoolExecutor(
                    max_workers=self._cores) as executor:
                models = executor.map(self.build_fn, px_parameters)
                fitnesses = executor.map(self.eval_fn, models)
        tars_fits = list(zip(targets, fitnesses))
        if self._store_params:
            self.parameter_log.append(
                    [(self.parse_individual(x[0]), x[1]) for x in tars_fits])
        for ind, fit in tars_fits:
            ind.fitness.values = (fit,)
        return

    def _generate(self):
        """Generates a particle using the creator function."""
        raise NotImplementedError("Will depend on optimizer type")

    def _initialize_pop(self):
        """Assigns indices to individuals in population."""
        raise NotImplementedError("Will depend on optimizer type")

    def _update_pop(self):
        """Updates population according to crossover and fitness criteria."""
        raise NotImplementedError("Will depend on optimizer type")

    def log_results(self, output_path=None, run_id=None):
        """Saves files for the minimization.

        Notes
        -----
        Currently saves a logfile with best individual and a pdb of
        the best model.
        """
        best_ind = self.halloffame[0]
        model_params = self.parse_individual(
            best_ind)  # need to change name of 'params'
        if output_path is None:
            output_path = os.getcwd()
        if run_id is None:
            run_id = '{:%Y%m%d-%H%M%S}'.format(
                datetime.datetime.now())
        with open('{0}/{1}_opt_log.txt'.format(
                output_path, run_id), 'w') as log_file:
            log_file.write('\nEvaluated {0} models in total\n'.format(
                self._model_count))
            log_file.write('Run ID is {0}\n'.format(run_id))
            log_file.write('Best fitness is {0}\n'.format(
                self.halloffame[0].fitness))
            log_file.write(
                'Parameters of best model are {0}\n'.format(model_params))
            log_file.write(
                'Best individual is {0}\n'.format(self.halloffame[0]))
            for i, entry in enumerate(self.halloffame[0]):
                if entry > 0.95:
                    log_file.write(
                        "Warning! Parameter {0} is at or near maximum allowed "
                        "value\n".format(i + 1))
                elif entry < -0.95:
                    log_file.write(
                        "Warning! Parameter {0} is at or near minimum allowed "
                        "value\n".format(i + 1))
            log_file.write('Minimization history: \n{0}'.format(self.logbook))
        with open('{0}/{1}_opt_best_model.pdb'.format(
                output_path, run_id), 'w') as output_file:
            output_file.write(self.best_model.pdb)
        return

    @property
    def best_model(self):
        """Rebuilds the top scoring model from an optimisation.

        Returns
        -------
        model: AMPAL
            Returns an AMPAL model of the top scoring parameters.

        Raises
        ------
        NameError:
            Raises a name error if the optimiser has not been run.
        """
        if not hasattr(self, 'halloffame'):
            raise NameError('No best model found, have you ran the optimiser?')
        model = self.build_fn(*self.parse_individual(self.halloffame[0]))
        model.pack_new_sequences(self.sequence)
        return model

    def make_energy_funnel_data(self, cores=1):
        """Compares models created during the minimisation to the best model.

        Returns
        -------
        energy_rmsd_gen: [(float, float, int)]
            A list of triples containing the BUFF score, RMSD to the
            top model and generation of a model generated during the
            minimisation.
        """
        if not self.parameter_log:
            raise AttributeError(
                'No parameter log data to make funnel, have you ran the '
                'optimiser?')
        model_cls = self.specification
        gen_tagged = []
        for gen, models in enumerate(self.parameter_log):
            for model in models:
                gen_tagged.append((model[0], model[1], gen))
        sorted_pps = sorted(gen_tagged, key=lambda x: x[1])
        top_result = sorted_pps[0]
        top_result_model = model_cls(*top_result[0])
        if (cores == 1) or (sys.platform == 'win32'):
            energy_rmsd_gen = map(
                self.funnel_rebuild,
                [(x, top_result_model, self.specification)
                 for x in sorted_pps[1:]])
        else:
            with futures.ProcessPoolExecutor(max_workers=cores) as executor:
                energy_rmsd_gen = executor.map(
                    self.funnel_rebuild,
                    [(x, top_result_model, self.specification)
                     for x in sorted_pps[1:]])
        return list(energy_rmsd_gen)

    @staticmethod
    def funnel_rebuild(psg_trm_spec):
        """Rebuilds a model and compares it to a reference model.

        Parameters
        ----------
        psg_trm: (([float], float, int), AMPAL, specification)
            A tuple containing the parameters, score and generation for a
            model as well as a model of the best scoring parameters.

        Returns
        -------
        energy_rmsd_gen: (float, float, int)
            A triple containing the BUFF score, RMSD to the top model
            and generation of a model generated during the minimisation.
        """
        param_score_gen, top_result_model, specification = psg_trm_spec
        params, score, gen = param_score_gen
        model = specification(*params)
        rmsd = top_result_model.rmsd(model)
        return rmsd, score, gen


class ParameterType(enum.Enum):
    """Type of parameter used in evolutionary optimizers."""
    STATIC_VALUE = 1
    DYNAMIC = 2


class Parameter:
    """Defines a parameter used in the evolutionary optimizers."""

    def __init__(self, label, parameter_type, value):
        self.label = label
        self.type = parameter_type
        self.value = value

    @classmethod
    def static(cls, label, value):
        return cls(label, Parameter.STATIC_VALUE, value)

    @classmethod
    def dynamic(cls, label, val_mean, val_range):
        return cls(label, Parameter.DISTRIBUTION, (val_mean, val_range))


__author__ = 'Andrew R. Thomson, Christopher W. Wood, Gail J. Bartlett'
