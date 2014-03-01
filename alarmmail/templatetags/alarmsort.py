"""Sort a list of AlarmEvents
"""

from django import template

register = template.Library()

class SbANode(template.Node):
    def __init__(self, input, output, attrs):
        self.input, self.output, self.attrs = input, output, attrs
    def render(self, context):
        input = self.input.resolve(context, True) # ignore failures
        out = self.output
        if not input:
            context[out] = []
            return

        def acmp(A, B):
            for attr in self.attrs:
                context[out] = A
                aA = attr.resolve(context, True)
                context[out] = B
                aB = attr.resolve(context, True)
                X = cmp(aA, aB)
                if X!=0:
                    return X
            return 0

        input = list(input) # ensure list and make a copy
        input.sort(cmp=acmp)
        context[out] = input
        return ''

@register.tag
def sortbyattr(parser, token):
    """Sort the provide list by the attribute(s) of its elements

    {% sortbyattr alist attr1.name attr2.name as sortedlist %}

    Will compare alist[0].attr1.name with alist[1].attr1.name
    then compare alist[0].attr2.name with alist[1].attr2.name
    """
    parts = token.split_contents()
    # [0] is 'sortbyattr'
    # [1] is the input variable name
    # [2:-2] are the attributes
    # [-2] is 'as'
    # [-1] is the output variable name
    if len(parts)<5:
        raise template.TemplateSyntaxError('sortbyattr takes at least 5 arguments')
    elif parts[-2] != 'as':
        raise template.TemplateSyntaxError('sortbyattr expects assignment "as" not %s'%parts[-2])
    outvar = parts[-1]
    # Borrow a trick from the regroup tag.
    # Reuse our output variable as a temperary
    exprs = [parser.compile_filter('%s.%s'%(outvar,e)) for e in parts[2:-2]]
    return SbANode(parser.compile_filter(parts[1]), outvar, exprs)
