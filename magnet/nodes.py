import torch
import magnet as mag

from torch import nn
from torch.nn import functional as F

from ._utils import caller_locals, get_function_name

class Node(nn.Module):
    def __init__(self, *args, **kwargs):
        input_shape = kwargs.pop('input_shape', None)
        self._parse_params()
        super().__init__()

        self._built = False

    def build(self, *args, **kwargs):
        self.to(mag.device)
        self._built = True

    def forward(self, *args, **kwargs):
        if not (self._built and mag.build_lock): self.build(*args, **kwargs)

    def parameters(self):
        import warnings
        if not self._built: raise RuntimeError(f'Node {self.name} not built yet')
        if not mag.build_lock: warnings.warn('Build-lock disabled. The node may be re-built', RuntimeWarning)

        return super().parameters()

    def named_parameters(self):
        import warnings
        if not self._built: raise RuntimeError(f'Node {self.name} not built yet')
        if not mag.build_lock: warnings.warn('Build-lock disabled. The node may be re-built', RuntimeWarning)

        return super().named_parameters()

    @property
    def _default_params(self):
        return {}

    def _parse_params(self):
        args = caller_locals(ancestor=True)
        if 'args' not in args.keys(): args['args'] = ()
        args['args'] = list(args['args'])
        if 'kwargs' not in args.keys(): args['kwargs'] = {}

        if len(args['args']) > 0 and type(args['args'][0]) is str:
            self.name = args['args'].pop(0)
        elif 'name' in args['kwargs'].keys():
            self.name = args['kwargs'].pop('name')
        else:
            self.name = self.__class__.__name__
        
        default_param_list = list(self._default_params.items())

        for i, arg_val in enumerate(args['args']):
            param_name = default_param_list[i][0]
            args[param_name] = arg_val
        args.pop('args')
        
        for param_name, default in default_param_list:
            if param_name in args['kwargs'].keys():
                args[param_name] = args['kwargs'][param_name]
            elif param_name not in args.keys():
                args[param_name] = default
        args.pop('kwargs')

        self._args = args

    def get_args(self):
        return ', '.join(str(k) + '=' + str(v) for k, v in self._args.items())

    def get_output_shape(self, in_shape):
        with torch.no_grad(): return tuple(self(torch.randn(in_shape)).size())

    def  _mul_int(self, n):
        return [self] + [self.__class__(**self._args) for _ in range(n - 1)]

    def  _mul_list(self, n):
        pass

    def __mul__(self, n):
        if type(n) is int or (type(n) is float and n.is_integer()):
            return self._mul_int(n)

        if type(n) is tuple or type(n) is list:
            return self._mul_list(n)

class MonoNode(Node):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._set_activation()

    def build(self, x):
        in_shape = x.shape

        layer_class = self._find_layer(in_shape)
        kwargs = self._get_kwargs(in_shape)
        self._layer = layer_class(**kwargs)
        
        super().build(in_shape)

    def forward(self, x):
        super().forward(x)
        return self._activation(self._layer(x))

    def _find_layer(self, in_shape):
        pass

    def _get_kwargs(self, in_shape):
        return {k: self._args[v] for k, v in self._kwargs_dict.items()}

    @property
    def _kwargs_dict(self):
        pass

    def _set_activation(self):
        from functools import partial

        activation_dict = {'relu': F.relu, 'sigmoid': F.sigmoid, 'tanh': F.tanh,
                            'lrelu': partial(F.leaky_relu, leak=0.2), None: lambda x: x}
        self._activation = activation_dict[self._args['act']]

    @property
    def _default_params(self):
        p = {'act': 'relu'}
        p.update(super()._default_params)
        return p

class Conv(MonoNode):
    def build(self, x):
        in_shape = x.shape
        self._set_padding(in_shape)
        super().build(x)

    def forward(self, x):
        if hasattr(self, '_upsample'): x = F.upsample(x, scale_factor=self._upsample)
        return super().forward(x)

    def _find_layer(self, in_shape):
        shape_dict = [nn.Conv1d, nn.Conv2d, nn.Conv3d]
        ndim = len(in_shape) - 2
        return shape_dict[ndim - 1]

    def _get_kwargs(self, in_shape):
        kwargs = super()._get_kwargs(in_shape)
        kwargs['in_channels'] = in_shape[1]
        return kwargs

    @property
    def _kwargs_dict(self):
        return {'kernel_size': 'k', 'out_channels': 'c','stride': 's',
                'padding': 'p', 'dilation': 'd', 'groups': 'g', 'bias': 'b'}
    
    def _set_padding(self, in_shape):
        p = self._args['p']
        if p == 'half': f = 0.5
        elif p == 'same': f = 1
        elif p == 'double':
            self._upsample = 2
            self._args['c'] = in_shape[1] // 2
            f = 1
        else: return
        
        s = 1 / f
        if not s.is_integer(): 
            raise RuntimeError("Padding value won't hold for all vector sizes")
            
        self._args['d'] = 1
        self._args['s'] = int(s)
        self._args['p'] = int(self._args['k'] // 2)
        if self._args['c'] is None: 
            self._args['c'] = self._args['s'] * in_shape[1]
        
    @property
    def _default_params(self):
        p = {'c': None, 'k': 3, 'p': 'half', 's': 1, 'd': 1, 'g': 1, 'b': True}
        p.update(super()._default_params)
        return p

    def  _mul_list(self, n):
        convs = [self]
        self._args['c'] = n[0]
        kwargs = self._args.copy()
        for c in n[1:]:
            kwargs['c'] = c
            convs.append(self.__class__(**kwargs))

        return convs

class Linear(MonoNode):
    def forward(self, x):
        if self._args['flat']: x = x.view(x.size(0), -1)

        return super().forward(x)

    def _find_layer(self, in_shape):
        return nn.Linear

    def _get_kwargs(self, in_shape):
        kwargs = super()._get_kwargs(in_shape)

        from numpy import prod
        kwargs['in_features'] = prod(in_shape[1:]) if self._args['flat'] else in_shape[-1]
        return kwargs

    @property
    def _kwargs_dict(self):
        return {'out_features': 'o', 'bias': 'b'}

    @property
    def _default_params(self):
        p = {'o': None, 'b': True, 'act': 'relu', 'flat': True}
        p.update(super()._default_params)
        return p

    def  _mul_list(self, n):
        lins = [self]
        self._args['o'] = n[0]
        kwargs = self._args.copy()
        for o in n[1:]:
            kwargs['o'] = o
            lins.append(self.__class__(**kwargs))

        return lins

class Lambda(Node):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

        self.name = get_function_name(fn)
        if self.name is None: self.name = 'Lambda'

    def forward(self, x):
        super().forward(x)
        return self.fn(x)