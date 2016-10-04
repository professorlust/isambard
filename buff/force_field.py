import json
import os

from settings import global_settings

force_fields = {}
for ff in os.listdir(os.path.join(global_settings['package_path'], 'buff', 'force_fields')):
    ffs = ff.split('.')
    if ffs[-1] == 'json':
        force_fields[ffs[0]] = os.path.join(global_settings['package_path'], 'buff', 'force_fields', ff)


class ForceFieldParameterError(Exception):
    pass


class BuffForceField(dict):
    _parameter_struct_dict = None
    _old_hash = None

    def __init__(self, force_field='standard', auto_update_params=False):
        with open(force_fields[force_field], 'r') as inf:
            in_d = json.loads(inf.read())
        super().__init__(in_d)
        self.force_field = force_field
        self.auto_update_f_params = auto_update_params

    def __repr__(self):
        return "<BUFF Force Field Object: {}>".format(self.force_field)

    @property
    def max_radius_and_npnp(self):
        return self.find_max_rad_npnp()

    @property
    def distance_cutoff(self):
        rad, npnp = self.find_max_rad_npnp()
        return (rad * 2) + npnp

    def find_max_rad_npnp(self):
        max_rad = 0
        max_npnp = 0
        for res, atoms in self.items():
            if res != 'KEY':
                for atom, ff_params in self[res].items():
                    if max_rad < ff_params[1]:
                        max_rad = ff_params[1]
                    if max_npnp < ff_params[4]:
                        max_npnp = ff_params[4]
        return max_rad, max_npnp

    @property
    def parameter_struct_dict(self):
        if self._parameter_struct_dict is None:
            self._parameter_struct_dict = self._make_ff_params_dict()
        elif self.auto_update_f_params:
            new_hash = hash(tuple([tuple(item) for sublist in self.values() for item in sublist.values()]))
            if self._old_hash != new_hash:
                self._parameter_struct_dict = self._make_ff_params_dict()
                self._old_hash = new_hash
        return self._parameter_struct_dict

    def _make_ff_params_dict(self):
        from buff import PyAtomData

        try:
            ff_params_struct_dict = {}
            for res in self.keys():
                if res == 'KEY':
                    continue
                if res not in ff_params_struct_dict:
                    ff_params_struct_dict[res] = {}
                for atom, params in self[res].items():
                    ff_params_struct_dict[res][atom] = PyAtomData(
                        atom.encode(), params[0].encode(), *params[1:])
        except TypeError:
            raise ForceFieldParameterError('Badly formatted force field parameters: {}'.format(params))
        return ff_params_struct_dict

global_settings[u'buff'][u'force_field'] = BuffForceField(
    force_field=global_settings[u'buff'][u'default_force_field'])
