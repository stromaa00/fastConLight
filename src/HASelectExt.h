#ifndef HASELECT_EXT_H
#define HASELECT_EXT_H

#include <ArduinoHA.h>
#include <tools.h>

// Add declarations for any extended functionality for HASelect
class HASelectExt : public HASelect
{
private:
    bool nameAllocated = false;
    char *mem_name; 
public:
    HASelectExt(const char *uniqueId) : HASelect(uniqueId) {}
    HASelectExt(String uniqueId) : HASelect(allocateAndCopy(&uniqueId)){};

    inline void rebind() { onMqttConnected(); };
    void setName(String name)
    {
        mem_name = allocateAndCopy(&name);
        HASelect::setName(mem_name);

    }

    
    ~HASelectExt()
    {
        if (nameAllocated)
        {
            free(mem_name);
        }

        delete uniqueId();
    }



};

#endif // HASELECT_EXT_H