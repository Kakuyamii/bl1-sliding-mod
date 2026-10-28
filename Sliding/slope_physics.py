pass
import math


def projected_acceleration(normal, direction, gravity, influence):
    nx,ny,nz = normal
    length = math.sqrt(nx*nx+ny*ny+nz*nz)
    if not .5 <= length <= 1.5:
        return 0.0
    nx,ny,nz = nx/length,ny/length,nz/length
    if nz < .65:
        return 0.0


    return max(0,min(4000,abs(gravity)))*nz*(nx*direction[0]+ny*direction[1])*influence
