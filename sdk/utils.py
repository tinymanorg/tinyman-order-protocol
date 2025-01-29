from tinyman.utils import int_to_bytes


# TODO: remove this and use from sdk.
def int_array(elements, size, default=0):
    array = [default] * size

    for i in range(len(elements)):
        array[i] = elements[i]
    bytes = b"".join(map(int_to_bytes, array))
    return bytes
