"""
Base classes needed for resource models support.
"""

import logging
LOG = logging.getLogger("resourcemodel")
LOG.setLevel(logging.DEBUG)


class ResourceModelRegistrar(object):
    """
    Global registry to keep track of all existing resource models.
    """

    def __init__(self, dc_emulation_max_cpu, dc_emulation_max_mem):
        self.e_cpu = dc_emulation_max_cpu
        self.e_mem = dc_emulation_max_mem
        # pointer to all resource models assigned to DCs
        self._resource_models = dict()
        LOG.info("Resource model registrar created with dc_emulation_max_cpu=%r and dc_emulation_max_mem=%r"
                 % (dc_emulation_max_cpu, dc_emulation_max_mem))

    def register(self, dc, rm):
        """
        Register a new resource model.
        :param dc: Data center to which it is assigned.
        :param rm: The resource model object.
        :return: None
        """
        if dc in self._resource_models:
            raise Exception("There is already an resource model assigned to this DC.")
        self._resource_models[dc] = rm
        rm.registrar = self
        rm.dcs.append(dc)
        LOG.info("Registrar: Added resource model: %r" % rm)

    @property
    def resource_models(self):
        """
        List of registered resource models
        :return:
        """
        return list(self._resource_models.itervalues())

    @property
    def num_dcs_with_rms(self):
        """
        Total number of data centers that are connected to a resource model
        :return:
        """
        return sum([len(rm.dcs) for rm in list(self._resource_models.itervalues())])


class ResourceFlavor(object):
    """
    Simple class that represents resource flavors (c.f. OpenStack).
    Can contain arbitrary metrics.
    """
    def __init__(self, name, metrics):
        self.name = name
        self._metrics = metrics
        LOG.debug("Create flavor %r with metrics: %r" % (name, metrics))

    def get(self, metric_key):
        return self._metrics.get(metric_key)


class BaseResourceModel(object):
    """
    Base class for a resource limitation model.
    Has to be extended by a real resource model implementtion.
    """

    def __init__(self):
        self._flavors = dict()
        self._initDefaultFlavors()
        self.registrar = None  # pointer to registrar
        self.dcs = list()
        self._allocated_compute_instances = dict()
        LOG.info("Resource model %r initialized" % self)

    def __repr__(self):
        return self.__class__.__name__

    def _initDefaultFlavors(self):
        """
        initialize some default flavours (naming/sizes inspired by OpenStack)
        """
        self.addFlavour(ResourceFlavor(
            "tiny",  {"compute": 0.5, "memory": 32, "disk": 1}))
        self.addFlavour(ResourceFlavor(
            "small",  {"compute": 1.0, "memory": 128, "disk": 20}))
        self.addFlavour(ResourceFlavor(
            "medium",  {"compute": 4.0, "memory": 256, "disk": 40}))
        self.addFlavour(ResourceFlavor(
            "large",  {"compute": 8.0, "memory": 512, "disk": 80}))
        self.addFlavour(ResourceFlavor(
            "xlarge",  {"compute": 16.0, "memory": 1024, "disk": 160}))

    def addFlavour(self, fl):
        """
        Add a new flavor to the resource model.
        :param fl: flavor object
        :return: None
        """
        if fl.name in self._flavors:
            raise Exception("Flavor with name %r already exists!" % fl.name)
        self._flavors[fl.name] = fl

    def allocate(self, d):
        """
        This method has to be overwritten by a real resource model.
        :param d: Container object
        """
        LOG.warning("Allocating in BaseResourceModel: %r with flavor: %r" % (d.name, d.flavor_name))
        self._allocated_compute_instances[d.name] = d.flavor_name

    def free(self, d):
        """
        This method has to be overwritten by a real resource model.
        :param d: Container object
        """
        LOG.warning("Free in BaseResourceModel: %r" % d.name)
        del self._allocated_compute_instances[d.name]

    def get_state_dict(self):
        """
        Return the state of the resource model as simple dict.
        Helper method for logging functionality.
        :return:
        """
        return dict()

    def write_allocation_log(self, d, path):
        """
        Helper to log RM info for experiments.
        :param d: container
        :param path: log path
        :return:
        """
        self._write_log(d, path, "allocate")

    def write_free_log(self, d, path):
        """
        Helper to log RM info for experiments.
        :param d: container
        :param path: log path
        :return:
        """
        self._write_log(d, path, "free")

    def _write_log(self, d, path, action):
        """
        Helper to log RM info for experiments.
        :param d: container
        :param path: log path
        :param action: allocate or free
        :return:
        """
        pass


class NotEnoughResourcesAvailable(BaseException):
    pass
