import magnet as mag

def summarize(module, x, parameters='trainable', arguments=False, batch=False, max_width=120):
    from torch.nn import Sequential
    from beautifultable import BeautifulTable
    from magnet.nodes import Node
    from magnet._utils import num_params

    def _handle_parameter_output(mode, node=None):
        str_dict = {'trainable': 'Trainable', 'non-trainable': 'NON-Trainable', 'all': '', True: '(Trainable, NON-Trainable)'}
        if mode == 'col': return str_dict[parameters] + ' Parameters'

        def _get_num_params(module):
            n = num_params(module) if module is not None else (0, 0)
            n_dict = {'trainable': n[0], 'non-trainable': n[1], 'all': sum(n), True: n}
            n = n_dict[parameters]
            return ', '.join(['{:,}'] * len(n)).format(*n) if type(n) is tuple else '{:,}'.format(n)

        if mode == 'row': return _get_num_params(node)

        print('Total ' + str_dict[parameters] + ' Parameters:', _get_num_params(module))

    _start_idx = 0 if batch else 1
    shape_sequence = [x.shape]
    children = list(module.children()) if isinstance(module, Sequential) else [module]
    for m in children:
        with mag.eval(m): x = m(x)
        shape_sequence.append(x.shape)
    shape_sequence = [', '.join(str(i) for i in s[_start_idx:]) for s in shape_sequence]


    table = BeautifulTable(max_width=max_width)
    column_headers = ['Node', 'Shape']
    if parameters is not False: column_headers.append(_handle_parameter_output('col'))

    if arguments: column_headers.append('Arguments')
    table.column_headers = column_headers

    row = ['input', shape_sequence[0]]
    if parameters is not False: row.append(_handle_parameter_output('row'))

    if arguments: row.append('')
    table.append_row(row)

    for node, shape in zip(children, shape_sequence[1:]):
        name = node.name if hasattr(node, 'name') else str(node).split('(')[0]

        row = [name, shape]
        if parameters is not False: row.append(_handle_parameter_output('row', node))

        if arguments:
            if isinstance(node, Node):row.append(node.get_args())
            else: row.append('')
        table.append_row(row)

    print(table)

    if parameters is not False: _handle_parameter_output('total')